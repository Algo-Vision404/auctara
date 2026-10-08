"""Pure, deterministic policy rule functions. No I/O, fully unit-testable."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Policy:
    max_transaction_amount: float
    approval_threshold: float
    daily_limit: float
    monthly_limit: float
    velocity_max_transactions: int = 5
    velocity_window_minutes: int = 60
    price_variance_tolerance: float = 0.05
    blocked_categories: list[str] = field(default_factory=list)
    allowed_categories: list[str] = field(default_factory=list)


@dataclass
class ProposalContext:
    amount: float
    category: str
    daily_spent: float
    monthly_spent: float
    transactions_in_window: int


DECISION_ALLOW = "ALLOW"
DECISION_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
DECISION_BLOCK = "BLOCK"


def normalize_category(category: str) -> str:
    return (category or "").strip().lower()


def category_blocked(policy: Policy, category: str) -> bool:
    c = normalize_category(category)
    return c in {x.lower() for x in policy.blocked_categories}


def category_not_allowed(policy: Policy, category: str) -> bool:
    if not policy.allowed_categories:
        return False
    c = normalize_category(category)
    return c not in {x.lower() for x in policy.allowed_categories}


def exceeds_daily_limit(policy: Policy, ctx: ProposalContext) -> bool:
    return (ctx.daily_spent + ctx.amount) > policy.daily_limit + 1e-9


def exceeds_monthly_limit(policy: Policy, ctx: ProposalContext) -> bool:
    return (ctx.monthly_spent + ctx.amount) > policy.monthly_limit + 1e-9


def exceeds_velocity(policy: Policy, ctx: ProposalContext) -> bool:
    return ctx.transactions_in_window >= policy.velocity_max_transactions


def exceeds_max_transaction(policy: Policy, ctx: ProposalContext) -> bool:
    return ctx.amount > policy.max_transaction_amount + 1e-9


def within_autonomous_authority(policy: Policy, ctx: ProposalContext) -> bool:
    return ctx.amount <= policy.approval_threshold + 1e-9


def price_within_tolerance(expected: float, actual: float, tolerance: float) -> bool:
    if expected <= 0:
        return True
    variance = abs(actual - expected) / expected
    return variance <= tolerance + 1e-9
