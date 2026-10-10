"""The deterministic policy engine.

This is the single authoritative place a spending decision is made.
It never consults the LLM and the LLM never calls it directly for
authorization. Only the backend transaction orchestrator does.
"""
from __future__ import annotations

from app.guardrails import rules
from app.guardrails.rules import Policy, ProposalContext


def evaluate(policy: Policy, ctx: ProposalContext) -> dict:
    """Return a structured decision dict, mirroring the product spec shape."""

    remaining_daily = round(policy.daily_limit - ctx.daily_spent, 2)
    remaining_monthly = round(policy.monthly_limit - ctx.monthly_spent, 2)

    # A blocked_categories entry that isn't one of the agent's fixed
    # classification categories (e.g. "gambling", "crypto" - see
    # _free_text_blocked_terms's docstring) can never be caught by
    # category_blocked(), which only ever compares against the exact
    # category the purchasing agent chose from its fixed enum. Computed
    # once up front so both the "checks" summary and the actual decision
    # below agree with each other.
    blocked_term = rules.blocked_term_match(policy, ctx)

    base = {
        "requested_amount": round(ctx.amount, 2),
        "authorized_amount": 0,
        "remaining_daily_budget": remaining_daily,
        "remaining_monthly_budget": remaining_monthly,
        "checks": {
            "category_allowed": not rules.category_blocked(policy, ctx.category)
            and not rules.category_not_allowed(policy, ctx.category)
            and blocked_term is None,
            "under_max_transaction": not rules.exceeds_max_transaction(policy, ctx),
            "daily_budget_available": not rules.exceeds_daily_limit(policy, ctx),
            "monthly_budget_available": not rules.exceeds_monthly_limit(policy, ctx),
            "velocity_ok": not rules.exceeds_velocity(policy, ctx),
        },
    }

    if rules.category_blocked(policy, ctx.category):
        return {
            **base,
            "decision": rules.DECISION_BLOCK,
            "reason": f"Category '{ctx.category}' is explicitly blocked by policy.",
        }

    if blocked_term is not None:
        return {
            **base,
            "decision": rules.DECISION_BLOCK,
            "reason": (
                f"This proposal matches the policy's blocked term '{blocked_term}' "
                f"(found in the merchant, product, or stated reason), even though it "
                f"was classified as category '{ctx.category}'."
            ),
        }

    if rules.category_not_allowed(policy, ctx.category):
        return {
            **base,
            "decision": rules.DECISION_BLOCK,
            "reason": f"Category '{ctx.category}' is not in the permitted category list.",
        }

    if rules.exceeds_velocity(policy, ctx):
        return {
            **base,
            "decision": rules.DECISION_BLOCK,
            "reason": (
                f"Transaction velocity limit exceeded: {ctx.transactions_in_window} "
                f"transactions already made within {policy.velocity_window_minutes} minutes "
                f"(limit {policy.velocity_max_transactions})."
            ),
        }

    if rules.exceeds_daily_limit(policy, ctx):
        return {
            **base,
            "decision": rules.DECISION_BLOCK,
            "reason": (
                f"Transaction would exceed daily spending limit of ${policy.daily_limit:,.2f} "
                f"(${ctx.daily_spent:,.2f} already spent today)."
            ),
        }

    if rules.exceeds_monthly_limit(policy, ctx):
        return {
            **base,
            "decision": rules.DECISION_BLOCK,
            "reason": (
                f"Transaction would exceed monthly spending limit of ${policy.monthly_limit:,.2f} "
                f"(${ctx.monthly_spent:,.2f} already spent this month)."
            ),
        }

    if rules.exceeds_max_transaction(policy, ctx):
        return {
            **base,
            "decision": rules.DECISION_BLOCK,
            "reason": (
                f"Transaction of ${ctx.amount:,.2f} exceeds the maximum transaction authority "
                f"of ${policy.max_transaction_amount:,.2f} granted to this agent."
            ),
        }

    if rules.within_autonomous_authority(policy, ctx):
        return {
            **base,
            "decision": rules.DECISION_ALLOW,
            "authorized_amount": round(ctx.amount, 2),
            "reason": (
                f"Transaction of ${ctx.amount:,.2f} is within the agent's autonomous "
                f"spending authority of ${policy.approval_threshold:,.2f}."
            ),
        }

    return {
        **base,
        "decision": rules.DECISION_APPROVAL_REQUIRED,
        "authorized_amount": round(ctx.amount, 2),
        "reason": (
            f"Transaction of ${ctx.amount:,.2f} exceeds the agent's autonomous spending "
            f"authority of ${policy.approval_threshold:,.2f} and requires human approval."
        ),
    }


def evaluate_price_variance(policy: Policy, expected: float, actual: float) -> dict:
    ok = rules.price_within_tolerance(expected, actual, policy.price_variance_tolerance)
    variance_pct = 0.0 if expected == 0 else abs(actual - expected) / expected * 100
    return {
        "within_tolerance": ok,
        "expected_amount": round(expected, 2),
        "actual_amount": round(actual, 2),
        "variance_pct": round(variance_pct, 2),
        "tolerance_pct": round(policy.price_variance_tolerance * 100, 2),
    }
