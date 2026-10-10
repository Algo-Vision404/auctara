"""Small/free LLMs have a well-known failure mode: asked for an optional
field it has no real value for, it writes the literal word "None" (or
"null"/"n/a"/...) as a string instead of simply omitting the key. That
string is not absent - proposal.get(...) returns it like any other real
value - so without sanitization it flows straight into the database and
back out to the ledger UI as if it were a genuine image/listing URL. A
frontend truthiness check (`tx.image_url && <img src=...>`) does not catch
it, since a non-empty string is truthy no matter what it says: the browser
ends up actually requesting the literal path "/None" as an <img> src,
which 404s. This reproduced live as a `GET /None 404` in the dev server
log with no corresponding user navigation.

This test proves the fix at the one place every proposal's optional
fields enter the system: orchestrator._clean_optional_str, applied when
the proposal is accepted in _continue_research.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.agent.orchestrator as orchestrator
from app.agent.orchestrator import _clean_optional_str, _is_blank_or_nullish
from app.main import app


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict):
        self.id = call_id
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments))


class FakeMessage:
    def __init__(self, tool_calls=None, content=None):
        self.tool_calls = tool_calls
        self.content = content

    def model_dump(self, exclude_none=True):
        data = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in self.tool_calls
            ]
        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}
        return data


class _SequentialCompletions:
    def __init__(self, messages):
        self._messages = list(messages)
        self._idx = 0

    async def create(self, **kwargs):
        msg = self._messages[min(self._idx, len(self._messages) - 1)]
        self._idx += 1
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _fake_client_sequence(messages):
    client = SimpleNamespace(chat=SimpleNamespace(completions=_SequentialCompletions(messages)))
    return lambda: client


def _permissive_agent(client: TestClient) -> dict:
    payload = {
        "name": "Shopping Agent",
        "purpose": "Find and buy software deals",
        "directive": "Find the best software plan deals for the team.",
        "policy": {
            "max_transaction_amount": 1500,
            "approval_threshold": 1500,
            "daily_limit": 3000,
            "monthly_limit": 10000,
            "allowed_categories": [],
        },
    }
    return client.post("/agents", json=payload).json()


def _poll_until(client: TestClient, task_id: str, statuses: set[str]) -> dict:
    task = None
    for _ in range(20):
        time.sleep(0.2)
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in statuses:
            break
    return task


def test_clean_optional_str_scrubs_known_sentinels():
    for junk in ["None", "none", "NONE", "null", "NULL", "n/a", "N/A", "undefined", "nil", "", "  none  "]:
        assert _clean_optional_str(junk) is None
    # Real values, including ones that merely contain a sentinel substring,
    # must pass through untouched.
    assert _clean_optional_str("https://example.com/none-of-the-above.png") == (
        "https://example.com/none-of-the-above.png"
    )
    assert _clean_optional_str("Nonesuch Books") == "Nonesuch Books"
    assert _clean_optional_str(None) is None


def test_is_blank_or_nullish_extends_the_required_field_check():
    for junk in ["None", "null", "N/A", "", None]:
        assert _is_blank_or_nullish(junk) is True
    assert _is_blank_or_nullish("Baremetrics") is False
    assert _is_blank_or_nullish(0) is False  # numeric amount, handled separately


def test_required_field_sentinel_string_is_bounced_back_not_accepted(monkeypatch):
    """The missing-field check for create_purchase_proposal's *required*
    fields (merchant/amount/currency/category/reason) only ever compared
    against `None`/`""`. If the model writes the literal string "None" for
    merchant - same failure mode as the optional fields, just on a field
    that gets displayed everywhere as real transaction data - that used to
    sail through as "present". It must instead be bounced back to the
    agent as a tool error (exactly like any other missing field), giving
    it a chance to self-correct, and a transaction must never end up with
    merchant/category literally equal to "None" in the database.
    """
    with TestClient(app) as client:
        agent = _permissive_agent(client)

        bad_proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "create_purchase_proposal",
            {
                "merchant": "None", "amount": 129.0, "currency": "USD",
                "category": "none", "reason": "Subscription analytics software.",
                "source_url": "https://baremetrics.com/pricing",
            },
        )])
        real_proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_2", "create_purchase_proposal",
            {
                "merchant": "Baremetrics", "amount": 129.0, "currency": "USD",
                "category": "software", "reason": "Subscription analytics software, real price found.",
                "source_url": "https://baremetrics.com/pricing",
            },
        )])
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([bad_proposal, real_proposal]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "EXECUTING"})

        tx = task["transactions"][0]
        assert tx["merchant"] != "None"
        assert tx["category"] != "none"
        assert tx["merchant"] == "Baremetrics"


def test_literal_none_string_from_the_model_never_reaches_the_stored_transaction(monkeypatch):
    """Reproduces the exact live bug: the model's tool call fills image_url,
    source_url and retailer with the literal string "None" instead of
    omitting them. The stored transaction must end up with real NULLs, not
    the string "None", so the ledger UI never tries to render/link to it.
    """
    with TestClient(app) as client:
        agent = _permissive_agent(client)

        async def _fake_research_loop(agent_, task_, tx_id_, messages_, categories_):
            return {
                "merchant": "Baremetrics",
                "amount": 129.0,
                "currency": "USD",
                "category": "software",
                "reason": "Subscription analytics software, real price found.",
                "source_url": "None",
                "image_url": "none",
                "retailer": "N/A",
                "channel3_product_id": "null",
            }

        monkeypatch.setattr(orchestrator, "_run_research_loop", _fake_research_loop)

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "EXECUTING"})

        tx = task["transactions"][0]
        assert tx["source_url"] is None
        assert tx["image_url"] is None
        assert tx["retailer"] is None
        assert tx["channel3_product_id"] is None
