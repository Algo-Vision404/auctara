from __future__ import annotations

from fastapi import APIRouter

from app.database import models

router = APIRouter()


@router.get("/dashboard/summary")
def summary():
    agents = models.list_agents()
    active_agents = [a for a in agents if a["status"] == "ACTIVE"]

    total_spent_today = 0.0
    total_remaining = 0.0
    awaiting_approval = 0

    for a in agents:
        policy = models.get_active_policy(a["id"])
        spent = models.get_spent_since(a["id"], models.start_of_day_iso())
        total_spent_today += spent
        if policy:
            total_remaining += max(policy["daily_limit"] - spent, 0)

    all_tx = models.list_transactions()
    awaiting_approval = len([t for t in all_tx if t["state"] == "AWAITING_APPROVAL"])
    completed_today = len([
        t for t in all_tx
        if t["state"] == "COMPLETED" and t["created_at"] >= models.start_of_day_iso()
    ])
    blocked_count = len([t for t in all_tx if t["state"] == "BLOCKED"])

    return {
        "active_agents": len(active_agents),
        "total_agents": len(agents),
        "spent_today": round(total_spent_today, 2),
        "remaining_today": round(total_remaining, 2),
        "awaiting_approval": awaiting_approval,
        "completed_today": completed_today,
        "blocked_count": blocked_count,
        "total_transactions": len(all_tx),
    }
