"""create_purchase_proposal's `category` field must be a hard JSON schema
enum scoped to the specific agent it's being built for, not just a
descriptive hint and not one list shared by every agent on the platform.

Without the enum, a model is free to invent a category string that no
policy could ever have been configured to allow/deny, silently turning a
correctly in-scope, correctly-researched purchase into an unfixable false
block. Without it being PER-AGENT, every agent on the platform is force-fit
into the same generic buckets regardless of what it actually buys (e.g. a
catering agent and a SaaS-subscriptions agent sharing one "food"/"software"
vocabulary neither of them fully fits) - this was explicit user-reported
feedback, not just a hypothetical.
"""
from __future__ import annotations

from app.agent.categories import FALLBACK_CATEGORIES
from app.agent.tools import build_tool_schemas


def _find_schema(schemas: list[dict], name: str) -> dict:
    for schema in schemas:
        if schema["function"]["name"] == name:
            return schema
    raise AssertionError(f"No tool schema named {name}")


def test_create_purchase_proposal_category_is_a_hard_enum_of_the_given_categories():
    custom = ["ingredients", "equipment", "delivery", "other"]
    schemas = build_tool_schemas(custom)
    schema = _find_schema(schemas, "create_purchase_proposal")
    category_prop = schema["function"]["parameters"]["properties"]["category"]
    assert category_prop.get("enum") == custom


def test_different_agents_get_different_category_vocabularies():
    # The whole point: two agents with different purposes must NOT be
    # forced into the same fixed, platform-wide category list.
    catering_schemas = build_tool_schemas(["ingredients", "equipment", "other"])
    saas_schemas = build_tool_schemas(["software", "subscriptions", "other"])
    catering_enum = _find_schema(catering_schemas, "create_purchase_proposal")["function"]["parameters"][
        "properties"
    ]["category"]["enum"]
    saas_enum = _find_schema(saas_schemas, "create_purchase_proposal")["function"]["parameters"]["properties"][
        "category"
    ]["enum"]
    assert catering_enum != saas_enum
    assert "ingredients" in catering_enum and "ingredients" not in saas_enum
    assert "software" in saas_enum and "software" not in catering_enum


def test_empty_categories_falls_back_to_legacy_list():
    # Agents created before per-agent categories existed (or a drafting
    # reply that genuinely produced none) must still get a usable, safe
    # enum instead of an empty/broken tool schema.
    schemas = build_tool_schemas([])
    schema = _find_schema(schemas, "create_purchase_proposal")
    assert schema["function"]["parameters"]["properties"]["category"]["enum"] == FALLBACK_CATEGORIES


def test_decline_out_of_scope_tool_is_registered():
    # Sanity check that the scope-decline tool from the agent-scope fix is
    # still wired into the schema list every research loop sees.
    _find_schema(build_tool_schemas(["software", "other"]), "decline_out_of_scope_task")
