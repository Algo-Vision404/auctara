"""Shared purchase-category vocabulary.

Both the purchasing agent's create_purchase_proposal tool (app/agent/tools.py)
and the policy drafting prompt (app/agent/policy_drafting.py) must agree on
the exact same fixed category list. Defining it once here means an
agent's allowed/blocked category lists are always expressed in the same
vocabulary the agent itself actually proposes purchases in, so a policy that
scopes an agent to e.g. "software" and "subscriptions" reliably matches (and
rejects) what the agent later proposes, instead of silently drifting apart if
either side's category list were edited independently.
"""
PURCHASE_CATEGORIES = [
    "software",
    "subscriptions",
    "office",
    "business",
    "hardware",
    "travel",
    "marketing",
    "other",
]
