from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.agent.orchestrator import emit, resume_task, run_task
from app.database import models
from app.paypal.orders import NEGATIVE_TEST_CODES
from app.streaming.events import sse_stream

router = APIRouter()


class CreateTaskRequest(BaseModel):
    agent_id: str
    prompt: str = Field(min_length=3)
    max_amount: float | None = None
    # Opt-in sandbox QA hook, off (None) for every normal task. When set, it
    # must be one of PayPal's own documented negative-testing codes (see
    # docs/NEGATIVE_TESTING.md) - never an arbitrary string - so the one
    # capture call this task makes gets a real, PayPal-sanctioned decline
    # response instead of a real capture, to demonstrate failure handling
    # on demand without fabricating any data ourselves.
    paypal_negative_test: str | None = None

    @field_validator("paypal_negative_test")
    @classmethod
    def _validate_negative_test(cls, v: str | None) -> str | None:
        if v and v not in NEGATIVE_TEST_CODES:
            raise ValueError(f"paypal_negative_test must be one of {sorted(NEGATIVE_TEST_CODES)}")
        return v


class TaskReplyRequest(BaseModel):
    message: str = Field(min_length=1)


def _browser_origin(request: Request) -> str | None:
    """Best-effort real origin of the browser that called this API, so PayPal's
    redirect back after checkout lands on whatever host/port the user is
    actually viewing the app from (localhost, a LAN IP, or a preview domain),
    never a hardcoded FRONTEND_URL that may not match in this environment."""
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


@router.get("/tasks/negative-test-options")
def negative_test_options():
    """The fixed set of PayPal-documented sandbox negative-testing codes a
    new task's `paypal_negative_test` may request (see
    docs/NEGATIVE_TESTING.md). Exposed so the frontend never hardcodes its
    own copy of this list."""
    return [{"code": code, "description": desc} for code, desc in NEGATIVE_TEST_CODES.items()]


@router.post("/tasks")
async def create_task(req: CreateTaskRequest, request: Request):
    agent = models.get_agent(req.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent["status"] != "ACTIVE":
        raise HTTPException(status_code=400, detail="Agent is not active")

    task = models.create_task(
        req.agent_id, req.prompt, req.max_amount, _browser_origin(request),
        paypal_negative_test=req.paypal_negative_test,
    )
    event_payload = {"prompt": req.prompt}
    if req.paypal_negative_test:
        event_payload["paypal_negative_test"] = req.paypal_negative_test
    await emit("TASK_CREATED", f"New task submitted to {agent['name']}.",
                task_id=task["id"], agent_id=agent["id"], payload=event_payload)

    asyncio.create_task(run_task(task["id"]))
    return task



@router.get("/tasks")
def list_tasks(agent_id: str | None = None):
    return models.list_tasks(agent_id)


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    task = models.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    transactions = [t for t in models.list_transactions(task["agent_id"]) if t["task_id"] == task_id]
    activity = models.list_activity(task_id=task_id, order="asc")
    return {**task, "transactions": transactions, "activity": activity}


@router.post("/tasks/{task_id}/respond")
async def respond_to_task(task_id: str, req: TaskReplyRequest):
    """Answer a task that is paused in NEEDS_INPUT because the agent's last
    turn was conversational (a clarifying question, or a check-in about a
    near-match it found) instead of a tool call. Resumes the same research
    loop with this reply appended to its exact prior conversation."""
    task = models.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tx = models.get_transaction_for_task(task_id)
    if not tx or tx["state"] != "NEEDS_INPUT":
        raise HTTPException(status_code=400, detail="This task is not currently waiting for a reply.")

    asyncio.create_task(resume_task(task_id, req.message))
    return {"status": "RESEARCHING"}


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str):
    return StreamingResponse(sse_stream(task_id), media_type="text/event-stream")


@router.get("/activity")
def recent_activity(limit: int = 50, task_id: str | None = None):
    # task_id scopes this to one task's own events (most-recent-first), so a
    # task execution view never shows other agents' unrelated activity while
    # waiting for its own live events to start arriving over SSE.
    return models.list_activity(task_id=task_id, limit=limit)


@router.get("/activity/stream")
async def activity_stream():
    return StreamingResponse(sse_stream(None), media_type="text/event-stream")
