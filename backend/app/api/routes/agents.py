from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agent.orchestrator import (
    AgentError,
    delete_agent as orchestrator_delete_agent,
    reactivate_agent,
    retire_agent,
)
from app.agent.policy_drafting import PolicyDraftError, PolicyNeedsClarification, draft_policy_step
from app.database import models

router = APIRouter()


class DraftPolicyRequest(BaseModel):
    # The very first call in a drafting conversation sends only
    # `instructions`. Continuing after a clarifying question sends back the
    # exact `conversation` the previous response returned, plus the
    # human's `answer` to append to it - there is no server-side session
    # for this (no agent record exists yet to hang one off), so the full
    # transcript round-trips through the client each time, the same
    # ownership split the main research loop uses for its own `messages`.
    instructions: str | None = Field(default=None, min_length=5)
    conversation: list[dict[str, str]] | None = None
    answer: str | None = None


class VelocityPayload(BaseModel):
    # window_start_iso(minutes) computes now minus this many minutes. A zero
    # or negative value pushes that window into the present or future, so
    # the "transactions in window" count comes back as zero no matter how
    # many transactions actually happened, silently turning off velocity
    # limiting instead of failing safe. Both fields must stay positive.
    max_transactions: int = Field(gt=0)
    window_minutes: int = Field(gt=0)


class PolicyPayload(BaseModel):
    max_transaction_amount: float = Field(gt=0)
    approval_threshold: float = Field(ge=0)
    daily_limit: float = Field(ge=0)
    monthly_limit: float = Field(ge=0)
    velocity: VelocityPayload = Field(default_factory=lambda: VelocityPayload(max_transactions=5, window_minutes=60))
    price_variance_tolerance: float = Field(default=0.05, ge=0)
    blocked_categories: list[str] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)
    # This agent's own fixed category vocabulary (what create_purchase_proposal's
    # `category` enum will be built from for this agent specifically - see
    # app/agent/tools.py build_tool_schemas). Normally comes straight from a
    # draft_policy_step() draft; defaults to [] (falls back to
    # FALLBACK_CATEGORIES at purchase time) only for agents created without
    # going through drafting.
    categories: list[str] = Field(default_factory=list)


class CreateAgentRequest(BaseModel):
    name: str
    purpose: str
    directive: str
    policy: PolicyPayload


@router.post("/agents/draft-policy")
async def draft_policy(req: DraftPolicyRequest):
    if req.conversation:
        conversation = list(req.conversation)
        if req.answer:
            conversation.append({"role": "user", "content": req.answer})
    elif req.instructions:
        conversation = [{"role": "user", "content": req.instructions}]
    else:
        raise HTTPException(status_code=400, detail="instructions or conversation is required")

    try:
        draft = await draft_policy_step(conversation)
    except PolicyNeedsClarification as clarification:
        return {
            "status": "needs_clarification",
            "question": clarification.question,
            "conversation": clarification.conversation,
        }
    except PolicyDraftError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "ready", "draft": draft}



@router.post("/agents")
def create_agent(req: CreateAgentRequest):
    if req.policy.max_transaction_amount < req.policy.approval_threshold:
        raise HTTPException(
            status_code=400,
            detail="max_transaction_amount must be greater than or equal to approval_threshold",
        )
    agent = models.create_agent(req.name, req.purpose, req.directive)
    policy = models.create_policy(agent["id"], req.policy.model_dump())
    return {**agent, "policy": policy}


@router.get("/agents")
def list_agents():
    agents = models.list_agents()
    out = []
    for a in agents:
        policy = models.get_active_policy(a["id"])
        out.append({**a, "policy": policy, **_agent_stats(a["id"], policy)})
    return out


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    agent = models.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    policy = models.get_active_policy(agent_id)
    transactions = models.list_transactions(agent_id)
    activity = [a for a in models.list_activity(limit=500) if a.get("agent_id") == agent_id][:50]
    return {
        **agent,
        "policy": policy,
        **_agent_stats(agent_id, policy),
        "transactions": transactions,
        "activity": activity,
    }


@router.post("/agents/{agent_id}/retire")
async def retire(agent_id: str):
    """Soft removal: stop this agent from accepting new tasks and cancel
    whatever it has in flight, while keeping its full history visible. See
    orchestrator.retire_agent for exactly what "in flight" covers."""
    try:
        agent = await retire_agent(agent_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    policy = models.get_active_policy(agent_id)
    return {**agent, "policy": policy, **_agent_stats(agent_id, policy)}


@router.post("/agents/{agent_id}/reactivate")
async def reactivate(agent_id: str):
    """The reverse of /retire: a RETIRED agent resumes accepting new tasks.
    Does not revive anything that was cancelled while it was retired - see
    orchestrator.reactivate_agent for exactly what does and doesn't come
    back."""
    try:
        agent = await reactivate_agent(agent_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    policy = models.get_active_policy(agent_id)
    return {**agent, "policy": policy, **_agent_stats(agent_id, policy)}


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Hard removal: cancels in-flight work, seals a final audit record, then
    permanently deletes the agent and everything that references it except
    the permanent, hash-chained audit trail (see orchestrator.delete_agent)."""
    try:
        await orchestrator_delete_agent(agent_id)
    except AgentError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}


def _agent_stats(agent_id: str, policy: dict | None) -> dict:
    daily_spent = models.get_spent_since(agent_id, models.start_of_day_iso())
    monthly_spent = models.get_spent_since(agent_id, models.start_of_month_iso())
    return {
        "daily_spent": round(daily_spent, 2),
        "monthly_spent": round(monthly_spent, 2),
        "daily_remaining": round((policy["daily_limit"] - daily_spent), 2) if policy else None,
        "monthly_remaining": round((policy["monthly_limit"] - monthly_spent), 2) if policy else None,
    }
