"""Pure, deterministic policy rule functions. No I/O, fully unit-testable."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.categories import FALLBACK_CATEGORIES


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
    # This agent's own fixed classification vocabulary - whatever
    # create_purchase_proposal's category enum was built from for this
    # specific agent (see app/agent/tools.py build_tool_schemas and
    # policy_drafting.py). Empty only for agents created before this field
    # existed; everywhere that needs a vocabulary to compare against should
    # fall back to FALLBACK_CATEGORIES in that case, never assume every
    # agent shares one platform-wide list.
    categories: list[str] = field(default_factory=list)


def _valid_categories(policy: Policy) -> set[str]:
    vocabulary = policy.categories or FALLBACK_CATEGORIES
    return {c.lower() for c in vocabulary}


@dataclass
class ProposalContext:
    amount: float
    category: str
    daily_spent: float
    monthly_spent: float
    transactions_in_window: int
    # Free text the proposal itself carries - merchant name, product name
    # (when known), and the agent's stated reason for picking it. Only used
    # by blocked_term_match below; every other rule in this module only
    # ever needs amount/category/spend history. Defaulted so every
    # existing caller (tests, the /policies/evaluate dry-run endpoint)
    # keeps working unchanged.
    merchant: str = ""
    product_name: str = ""
    reason: str = ""


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


def _free_text_blocked_terms(policy: Policy) -> list[str]:
    """blocked_categories entries that are NOT one of this agent's own
    fixed classification categories (policy.categories - see
    app/agent/categories.py for the legacy fallback).

    The policy-drafting prompt explicitly tells its own model to put
    whatever specific thing the user actually named here - e.g. a user who
    says "never buy gambling or crypto" gets blocked_categories =
    ["gambling", "crypto"] - but create_purchase_proposal's own `category`
    argument is a hard enum built from this specific agent's own category
    list, and a term like "gambling" or "crypto" generally isn't one of
    them. category_blocked() above can only ever compare against the
    literal category string the purchasing agent chose, so for a term like
    this there is no amount the agent proposes a gambling purchase as some
    other bucket that could ever make category_blocked() true - the
    exclusion the user explicitly asked for would silently do nothing,
    forever, with no error or warning anywhere. This is the one example the
    product's own "Create an Agent" page ships as its default instructions
    text.

    For entries that genuinely are one of this agent's real categories
    (e.g. blocked_categories containing "software"), category_blocked()
    already provides real, exact protection - returning those here too
    would only add false-positive risk (a legitimate "software" purchase
    whose merchant name happens to contain an unrelated blocked term as a
    substring) for a case that was never actually broken.
    """
    valid = _valid_categories(policy)
    return [c for c in policy.blocked_categories if c and c.strip().lower() not in valid]


def blocked_term_match(policy: Policy, ctx: ProposalContext) -> str | None:
    """Returns the first free-text blocked term (see above) that literally
    appears in this proposal's merchant/product_name/reason text, or None.

    This is a deliberately simple substring safety net, not a semantic
    classifier: it only catches a blocked word that is actually spelled
    out somewhere in the proposal (e.g. a merchant literally named "Crypto
    Exchange Co", or a reason that says "deposit to a gambling account").
    It will not infer that "DraftKings" means gambling or that "Coinbase"
    means crypto - no fixed keyword list ever could, reliably. What it
    does fix is the previous total absence of any enforcement whatsoever
    for exactly the kind of exclusion a user is most likely to type in
    plain language, where before this nothing could ever have blocked it,
    not even the one example case.
    """
    terms = _free_text_blocked_terms(policy)
    if not terms:
        return None
    haystack = " ".join(
        part for part in (ctx.merchant, ctx.product_name, ctx.reason) if part
    ).lower()
    if not haystack:
        return None
    for term in terms:
        t = term.strip().lower()
        if t and t in haystack:
            return term
    return None


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
