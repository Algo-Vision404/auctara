"""Helpers for turning stored DB policy rows into Policy objects and for
computing the live budget/velocity context a proposal must be judged against.
"""
from __future__ import annotations

from app.database import models
from app.guardrails.rules import Policy, ProposalContext


def policy_from_row(row: dict) -> Policy:
    return Policy(
        max_transaction_amount=row["max_transaction_amount"],
        approval_threshold=row["approval_threshold"],
        daily_limit=row["daily_limit"],
        monthly_limit=row["monthly_limit"],
        velocity_max_transactions=row["velocity_max_transactions"],
        velocity_window_minutes=row["velocity_window_minutes"],
        price_variance_tolerance=row["price_variance_tolerance"],
        blocked_categories=row["blocked_categories"],
        allowed_categories=row["allowed_categories"],
    )


def build_context(agent_id: str, amount: float, category: str, policy: Policy) -> ProposalContext:
    daily_spent = models.get_spent_since(agent_id, models.start_of_day_iso())
    monthly_spent = models.get_spent_since(agent_id, models.start_of_month_iso())
    window_count = models.count_transactions_since(
        agent_id, models.window_start_iso(policy.velocity_window_minutes)
    )
    return ProposalContext(
        amount=amount,
        category=category,
        daily_spent=daily_spent,
        monthly_spent=monthly_spent,
        transactions_in_window=window_count,
    )


DEFAULT_POLICY = {
    "max_transaction_amount": 150,
    "approval_threshold": 100,
    "daily_limit": 300,
    "monthly_limit": 2000,
    "velocity": {"max_transactions": 5, "window_minutes": 60},
    "price_variance_tolerance": 0.05,
    "blocked_categories": ["gambling", "crypto", "adult"],
    "allowed_categories": [],
}
