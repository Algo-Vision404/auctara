"""End-to-end proof of the gap fixed in app/guardrails/rules.py +
app/guardrails/engine.py: a blocked_categories entry that isn't one of the
purchasing agent's fixed 9 classification categories (software,
subscriptions, office, business, hardware, travel, marketing, food, other)
used to have no way to ever actually block anything.

"gambling" and "crypto" are the exact pair the product's own "Create an
Agent" page ships as its default example instructions
(frontend/src/app/agents/new/page.tsx: "Never buy gambling or crypto
products.", with the Blocked Categories field's own placeholder literally
reading "gambling, crypto"). Before this fix, an agent created from that
exact example text offered zero real protection against either: the
purchasing agent's create_purchase_proposal category argument can only ever
be one of the 9 fixed values, so category_blocked() comparing ctx.category
against "gambling"/"crypto" could never be true - any such purchase would
always have been classified as "other" and sailed straight through.

This exercises the real orchestrator + policy engine end-to-end, with only
the OpenRouter network call faked out, the same pattern used by
test_agent_scope.py.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.agent.orchestrator as orchestrator
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


class _FakeCompletions:
    def __init__(self, message: FakeMessage):
        self._message = message

    async def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=self._message)])


class _FakeClient:
    def __init__(self, message: FakeMessage):
        self.chat = SimpleNamespace(completions=_FakeCompletions(message))


def _fake_client_returning(message: FakeMessage):
    return lambda: _FakeClient(message)


def _run_task_until_terminal(client: TestClient, task_id: str) -> dict:
    task = None
    for _ in range(20):
        time.sleep(0.25)
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in ("BLOCKED", "COMPLETED", "FAILED", "AWAITING_APPROVAL", "VOIDED"):
            break
    return task


def _general_purpose_agent_with_gambling_crypto_blocked(client: TestClient) -> dict:
    """The exact default example from the "Create an Agent" page: broad
    purchasing authority (no allowed_categories restriction) with
    blocked_categories set to precisely what that page's own placeholder
    suggests typing."""
    payload = {
        "name": "General Purchasing Agent",
        "purpose": "Handle general company purchasing",
        "directive": "Buy whatever the team needs. Never buy gambling or crypto products.",
        "policy": {
            "max_transaction_amount": 150,
            "approval_threshold": 100,
            "daily_limit": 300,
            "monthly_limit": 2000,
            "blocked_categories": ["gambling", "crypto"],
        },
    }
    return client.post("/agents", json=payload).json()


def test_gambling_purchase_is_now_actually_blocked_despite_the_category_enum(monkeypatch):
    """The purchasing agent has no "gambling" category to pick from, so a
    real gambling purchase can only ever be proposed as category="other".
    Before this fix that meant blocked_categories=["gambling"] blocked
    nothing, ever. The merchant name itself names what it is, which is the
    realistic case blocked_term_match exists to catch."""
    with TestClient(app) as client:
        agent = _general_purpose_agent_with_gambling_crypto_blocked(client)

        proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "create_purchase_proposal",
            {
                "merchant": "DraftKings Gambling", "amount": 50, "currency": "USD",
                "category": "other", "reason": "User asked to fund their account",
                "source_url": "https://draftkings.com/deposit",
            },
        )])
        monkeypatch.setattr(orchestrator, "_openrouter_client", _fake_client_returning(proposal))

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Put $50 into my DraftKings account"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        tx = task["transactions"][0]
        assert tx["decision"] == "BLOCK"
        assert "gambling" in tx["decision_reason"].lower()


def test_unrelated_other_category_purchase_still_goes_through(monkeypatch):
    """Sanity check the other direction: the same policy must not start
    blocking every category="other" purchase just because that's the
    bucket a blocked free-text term would have to hide in."""
    with TestClient(app) as client:
        agent = _general_purpose_agent_with_gambling_crypto_blocked(client)

        proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "create_purchase_proposal",
            {
                "merchant": "Office Depot", "amount": 50, "currency": "USD",
                "category": "other", "reason": "Bulk printer paper restock",
                "source_url": "https://officedepot.com/paper",
            },
        )])
        monkeypatch.setattr(orchestrator, "_openrouter_client", _fake_client_returning(proposal))

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Order printer paper"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        tx = task["transactions"][0]
        assert tx["decision"] == "ALLOW"
