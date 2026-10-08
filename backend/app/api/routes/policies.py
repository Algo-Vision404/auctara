from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database import models
from app.guardrails import engine as policy_engine
from app.guardrails.policies import build_context, policy_from_row

router = APIRouter()


class EvaluateRequest(BaseModel):
    agent_id: str
    amount: float = Field(gt=0)
    category: str


@router.post("/policies/evaluate")
def evaluate(req: EvaluateRequest):
    """Dry-run policy evaluation. Does NOT reserve budget or create a transaction.
    Used by the UI to preview what would happen to a hypothetical proposal."""
    policy_row = models.get_active_policy(req.agent_id)
    if not policy_row:
        raise HTTPException(status_code=404, detail="No active policy for this agent")
    policy = policy_from_row(policy_row)
    ctx = build_context(req.agent_id, req.amount, req.category, policy)
    return policy_engine.evaluate(policy, ctx)


@router.get("/policies/{agent_id}")
def get_policy(agent_id: str):
    policy = models.get_active_policy(agent_id)
    if not policy:
        raise HTTPException(status_code=404, detail="No active policy for this agent")
    return policy


class UpdatePolicyRequest(BaseModel):
    max_transaction_amount: float
    approval_threshold: float
    daily_limit: float
    monthly_limit: float
    velocity: dict = Field(default_factory=lambda: {"max_transactions": 5, "window_minutes": 60})
    price_variance_tolerance: float = 0.05
    blocked_categories: list[str] = Field(default_factory=list)
    allowed_categories: list[str] = Field(default_factory=list)


@router.put("/policies/{agent_id}")
def update_policy(agent_id: str, req: UpdatePolicyRequest):
    agent = models.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if req.max_transaction_amount < req.approval_threshold:
        raise HTTPException(status_code=400, detail="max_transaction_amount must be >= approval_threshold")
    conn_policy = models.create_policy(agent_id, req.model_dump())
    return conn_policy
