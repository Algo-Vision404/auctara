from __future__ import annotations

from fastapi import APIRouter

from app.audit.integrity import list_audit, verify_chain

router = APIRouter()


@router.get("/audit")
def get_audit(transaction_id: str | None = None, limit: int = 200):
    return list_audit(transaction_id=transaction_id, limit=limit)


@router.get("/audit/verify")
def verify():
    return verify_chain()
