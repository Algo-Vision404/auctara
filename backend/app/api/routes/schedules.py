"""Agent Operations Schedule: persisted recurring delegated-commerce tasks.

A scheduled task is a standing instruction ("renew our analytics
subscription every month if the price stays below $100") that the
scheduler loop (app/scheduler.py) actually fires through the normal
research -> proposal -> policy -> approval -> PayPal pipeline when due.
Nothing here is simulated: every row is a real DB record, and every
"next run" visibly becomes a real task when its time arrives.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import models

router = APIRouter()

RECURRENCE_CHOICES = {"ONCE", "DAILY", "WEEKLY", "MONTHLY"}


class CreateScheduleRequest(BaseModel):
    agent_id: str
    prompt: str = Field(min_length=3)
    max_amount: float | None = None
    recurrence: str = "ONCE"
    start_at: str | None = None  # ISO 8601; defaults to now


class UpdateScheduleRequest(BaseModel):
    status: str | None = None  # ACTIVE, PAUSED, CANCELLED


@router.post("/schedules")
def create_schedule(req: CreateScheduleRequest):
    agent = models.get_agent(req.agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if req.recurrence not in RECURRENCE_CHOICES:
        raise HTTPException(status_code=400, detail=f"recurrence must be one of {sorted(RECURRENCE_CHOICES)}")

    start_at = req.start_at
    if start_at:
        try:
            # Normalize to the storage format used by now_iso().
            parsed = datetime.fromisoformat(start_at.replace("Z", "+00:00")).astimezone(timezone.utc)
            start_at = parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            raise HTTPException(status_code=400, detail="start_at must be a valid ISO 8601 datetime")
    else:
        start_at = models.now_iso()

    return models.create_scheduled_task(req.agent_id, req.prompt, req.max_amount, req.recurrence, start_at)


@router.get("/schedules")
def list_schedules(agent_id: str | None = None):
    return models.list_scheduled_tasks(agent_id)


@router.get("/schedules/{sched_id}")
def get_schedule(sched_id: str):
    sched = models.get_scheduled_task(sched_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return sched


@router.patch("/schedules/{sched_id}")
def update_schedule(sched_id: str, req: UpdateScheduleRequest):
    sched = models.get_scheduled_task(sched_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    if req.status and req.status not in {"ACTIVE", "PAUSED", "CANCELLED"}:
        raise HTTPException(status_code=400, detail="status must be ACTIVE, PAUSED, or CANCELLED")
    if not req.status:
        return sched
    # COMPLETED and CANCELLED are true terminal states (see
    # models.SCHEDULE_STATUS_EDGES's docstring): reactivating a schedule
    # that already fired for good would leave its next_run_at in the past,
    # which the scheduler would then see as due all over again on its very
    # next tick, firing a second real task - and a second real PayPal
    # purchase attempt - for an occurrence that already completed.
    updated = models.transition_schedule_status(sched_id, req.status)
    if updated is None:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot move this schedule from {sched['status']} to {req.status}.",
        )
    return updated


@router.get("/schedules/{sched_id}/runs")
def get_schedule_runs(sched_id: str):
    sched = models.get_scheduled_task(sched_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return models.list_runs_for_schedule(sched_id)


@router.delete("/schedules/{sched_id}")
def delete_schedule(sched_id: str):
    sched = models.get_scheduled_task(sched_id)
    if not sched:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    models.delete_scheduled_task(sched_id)
    return {"deleted": True}
