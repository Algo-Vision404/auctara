"""Legacy/fallback purchase-category vocabulary.

Category classification is no longer a single fixed list shared by every
agent on the platform. Each agent now gets its OWN closed vocabulary,
generated at drafting time to actually fit what that specific agent buys
(see policy_drafting.py's "categories" field and Policy.categories in
app/guardrails/rules.py) and stored with its policy. A catering agent and a
SaaS-subscriptions agent no longer have to be force-fit into the same 9
generic buckets.

The list below now exists ONLY as a safety-net fallback for the narrow case
where a per-agent category list isn't available - either an agent created
before this change (its stored policy.categories is empty), or the drafting
model, against instructions, failed to produce one. It is deliberately NOT
imported by the purchasing tool schema or the drafting prompt as "the"
category list anymore; callers that need a vocabulary should prefer the
agent's own policy.categories and only reach for this as a last resort.
"""
FALLBACK_CATEGORIES = [
    "software",
    "subscriptions",
    "office",
    "business",
    "hardware",
    "travel",
    "marketing",
    "food",
    "other",
]
