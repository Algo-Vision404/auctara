"""The create_purchase_proposal tool's `category` field must be a hard JSON
schema enum tied to the single shared PURCHASE_CATEGORIES vocabulary, not
just a descriptive hint. Without the enum, a model is free to invent a
category string (e.g. "food") that no policy could ever have been
configured to allow/deny, silently turning a correctly in-scope,
correctly-researched purchase into an unfixable false block. This was a
real bug: see categories.py's "food" entry, added after exactly this
failure mode was observed live against a food-purchasing agent.
"""
from __future__ import annotations

from app.agent.categories import PURCHASE_CATEGORIES
from app.agent.tools import TOOL_SCHEMAS


def _find_schema(name: str) -> dict:
    for schema in TOOL_SCHEMAS:
        if schema["function"]["name"] == name:
            return schema
    raise AssertionError(f"No tool schema named {name}")


def test_create_purchase_proposal_category_is_a_hard_enum():
    schema = _find_schema("create_purchase_proposal")
    category_prop = schema["function"]["parameters"]["properties"]["category"]
    assert category_prop.get("enum") == PURCHASE_CATEGORIES


def test_food_is_a_real_category_not_forced_into_other():
    # Regression guard for the specific bug: a dedicated purchasing purpose
    # (e.g. "buy food and find better food prices") must have its own
    # category rather than being indistinguishable from a catch-all "other"
    # bucket, which made it impossible for a policy to scope an agent to
    # food purchases specifically.
    assert "food" in PURCHASE_CATEGORIES
    assert "other" in PURCHASE_CATEGORIES


def test_decline_out_of_scope_tool_is_registered():
    # Sanity check that the scope-decline tool from the agent-scope fix is
    # still wired into the schema list every research loop sees.
    _find_schema("decline_out_of_scope_task")
