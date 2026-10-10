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


def ctx(amount, category="software", daily_spent=0, monthly_spent=0, window=0,
        merchant="", product_name="", reason="") -> ProposalContext:
    return ProposalContext(amount=amount, category=category, daily_spent=daily_spent,
                            monthly_spent=monthly_spent, transactions_in_window=window,
                            merchant=merchant, product_name=product_name, reason=reason)


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


# The test above passes category="gambling" directly, which is useful for
# exercising category_blocked() in isolation, but is NOT how a real
# proposal ever looks: create_purchase_proposal's own category argument is
# a hard enum of exactly 9 fixed values (software, subscriptions, office,
# business, hardware, travel, marketing, food, other) - "gambling" is never
# a legal value there, so a real gambling purchase could only ever be
# classified as "other". Without blocked_term_match, make_policy()'s own
# default blocked_categories=["gambling", "crypto"] - the exact example the
# product's "Create an Agent" page ships as its default instructions text -
# would never block a single real transaction, regardless of what it
# actually was, because ctx.category could never equal either word. These
# next few tests exercise that realistic shape instead.
def test_blocked_free_text_term_matches_a_realistic_proposal():
    policy = make_policy()  # blocked_categories=["gambling", "crypto"]
    result = evaluate(policy, ctx(
        10, category="other",  # the only enum value a real gambling purchase could ever get
        merchant="DraftKings Gambling", reason="User asked to fund their account",
    ))
    assert result["decision"] == DECISION_BLOCK
    assert "gambling" in result["reason"].lower()


def test_blocked_free_text_term_matches_via_reason_text_too():
    policy = make_policy()
    result = evaluate(policy, ctx(
        10, category="other", merchant="Example Corp",
        reason="Deposit requested for a crypto trading account",
    ))
    assert result["decision"] == DECISION_BLOCK
    assert "crypto" in result["reason"].lower()


def test_unrelated_proposal_in_the_same_category_is_not_blocked():
    """Sanity check: blocked_term_match must not fire on every "other"
    proposal just because that's the category a blocked term would have to
    hide behind - only on ones that actually mention a blocked term."""
    policy = make_policy()
    result = evaluate(policy, ctx(10, category="other", merchant="Office Depot",
                                   reason="Bulk printer paper restock"))
    assert result["decision"] == DECISION_ALLOW


def test_blocked_term_that_is_also_a_real_category_does_not_cause_false_positives():
    """A blocked_categories entry that genuinely IS one of the fixed
    categories (e.g. "food") already gets real, exact protection from
    category_blocked() - blocked_term_match must not ALSO scan for it as a
    substring, or a merchant name that coincidentally contains the word
    would wrongly block an unrelated, legitimate purchase."""
    policy = make_policy(blocked_categories=["food"])
    result = evaluate(policy, ctx(
        10, category="software", merchant="Foodimports Software Co",
        reason="Annual license renewal",
    ))
    assert result["decision"] == DECISION_ALLOW


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
