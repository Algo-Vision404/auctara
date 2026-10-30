from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agent.orchestrator import (
    AgentError,
    approve_transaction,
    check_paypal_order_progress,
    continue_after_paypal_approval,
    reject_transaction,
)
from app.audit.integrity import list_audit
from app.database import models

router = APIRouter()


@router.get("/transactions")
def list_transactions(agent_id: str | None = None, state: str | None = None, decision: str | None = None):
    rows = models.list_transactions(agent_id)
    if state:
        rows = [r for r in rows if r["state"] == state]
    if decision:
        rows = [r for r in rows if r["decision"] == decision]
    return rows


@router.get("/transactions/{tx_id}")
def get_transaction(tx_id: str):
    tx = models.get_transaction(tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    timeline = list_audit(transaction_id=tx_id)
    return {**tx, "timeline": timeline}


@router.get("/transactions/{tx_id}/timeline")
def get_timeline(tx_id: str):
    tx = models.get_transaction(tx_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return list_audit(transaction_id=tx_id)


class RejectRequest(BaseModel):
    reason: str | None = None


@router.post("/transactions/{tx_id}/approve")
async def approve(tx_id: str):
    try:
        return await approve_transaction(tx_id)
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/transactions/{tx_id}/reject")
async def reject(tx_id: str, req: RejectRequest | None = None):
    reason = (req.reason if req and req.reason else None) or "Rejected by user"
    try:
        return await reject_transaction(tx_id, reason)
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/transactions/{tx_id}/paypal/continue")
async def paypal_continue(tx_id: str):
    try:
        return await continue_after_paypal_approval(tx_id)
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/transactions/{tx_id}/paypal/check")
async def paypal_check(tx_id: str):
    """Polled repeatedly by the frontend while a transaction waits in
    VERIFYING for the buyer to approve at PayPal, so the original app tab
    can notice completion on its own - see check_paypal_order_progress's
    docstring for why this has to be a distinct, always-safe-to-call
    endpoint rather than just reusing /paypal/continue for this."""
    try:
        return await check_paypal_order_progress(tx_id)
    except AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
