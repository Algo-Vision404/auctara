from app.guardrails.engine import evaluate, evaluate_price_variance
from app.guardrails.rules import Policy, ProposalContext, DECISION_ALLOW, DECISION_APPROVAL_REQUIRED, DECISION_BLOCK


def make_policy(**overrides) -> Policy:
    base = dict(
        max_transaction_amount=150,
        approval_threshold=100,
        daily_limit=300,
        monthly_limit=2000,
        velocity_max_transactions=5,
        velocity_window_minutes=60,
        price_variance_tolerance=0.05,
        blocked_categories=["gambling", "crypto"],
        allowed_categories=[],
    )
    base.update(overrides)
    return Policy(**base)


def ctx(amount, category="software", daily_spent=0, monthly_spent=0, window=0) -> ProposalContext:
    return ProposalContext(amount=amount, category=category, daily_spent=daily_spent,
                            monthly_spent=monthly_spent, transactions_in_window=window)


def test_allowed_amount_within_autonomous_authority():
    policy = make_policy()
    result = evaluate(policy, ctx(63.99))
    assert result["decision"] == DECISION_ALLOW
    assert result["authorized_amount"] == 63.99


def test_amount_above_threshold_requires_approval():
    policy = make_policy()
    result = evaluate(policy, ctx(149))
    assert result["decision"] == DECISION_APPROVAL_REQUIRED


def test_amount_above_max_transaction_is_blocked():
    policy = make_policy(daily_limit=2000, monthly_limit=10000)
    result = evaluate(policy, ctx(420))
    assert result["decision"] == DECISION_BLOCK
    assert "maximum transaction authority" in result["reason"]


def test_blocked_category():
    policy = make_policy()
    result = evaluate(policy, ctx(10, category="gambling"))
    assert result["decision"] == DECISION_BLOCK
    assert "blocked" in result["reason"]


def test_category_not_in_allow_list():
    policy = make_policy(allowed_categories=["software"])
    result = evaluate(policy, ctx(10, category="travel"))
    assert result["decision"] == DECISION_BLOCK


def test_category_in_allow_list_passes():
    policy = make_policy(allowed_categories=["software"])
    result = evaluate(policy, ctx(10, category="software"))
    assert result["decision"] == DECISION_ALLOW


def test_daily_limit_enforced():
    policy = make_policy()
    result = evaluate(policy, ctx(50, daily_spent=280))
    assert result["decision"] == DECISION_BLOCK
    assert "daily spending limit" in result["reason"]


def test_monthly_limit_enforced():
    policy = make_policy()
    result = evaluate(policy, ctx(50, monthly_spent=1980))
    assert result["decision"] == DECISION_BLOCK
    assert "monthly spending limit" in result["reason"]


def test_velocity_limit_enforced():
    policy = make_policy(velocity_max_transactions=3)
    result = evaluate(policy, ctx(10, window=3))
    assert result["decision"] == DECISION_BLOCK
    assert "velocity" in result["reason"].lower()


def test_remaining_budget_reported():
    policy = make_policy()
    result = evaluate(policy, ctx(50, daily_spent=100, monthly_spent=500))
    assert result["remaining_daily_budget"] == 200
    assert result["remaining_monthly_budget"] == 1500


def test_price_variance_within_tolerance():
    policy = make_policy()
    result = evaluate_price_variance(policy, expected=79.99, actual=81.99)
    assert result["within_tolerance"] is True


def test_price_variance_exceeds_tolerance():
    policy = make_policy()
    result = evaluate_price_variance(policy, expected=79.99, actual=129.99)
    assert result["within_tolerance"] is False
