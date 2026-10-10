"""Channel3's catalog is real, physical retail inventory - every candidate
it returns comes from an actual online retailer's stock, with a real price
and buy_url (see app/search/channel3.py's own docstring). It has never
carried software, SaaS, licenses, or any other purely digital good.

This was a real, observed failure: a "SaaS Subscription Manager" agent
asked to renew "team management software" searched Channel3 three times
and got back a page of Marvel/Star Wars/Boston Red Sox t-shirts, because
the catalog's semantic match latched onto the word "team" - there was
never going to be a relevant result, because software simply isn't in that
index. The model eventually gave up and used search_web instead (so no
actual purchase was ever wrong), but every one of those calls was a wasted
real API round trip, and the irrelevant candidates stayed in the task's
audit trail and the transaction page's "Channel3 Product Research" panel
looking like real candidates for a purchase they had nothing to do with.

The fix is deterministic, not a prompt tweak: a clearly software/SaaS/
digital-subscription query is rejected before the real Channel3 API is
ever called, with a clear message steering the model to search_web.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
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


def _saas_agent(client: TestClient) -> dict:
    payload = {
        "name": "SaaS Subscription Manager",
        "purpose": "Manage our SaaS subscriptions",
        "directive": "Manage our SaaS subscriptions. You can spend up to $100 without asking.",
        "policy": {
            "max_transaction_amount": 150,
            "approval_threshold": 100,
            "daily_limit": 300,
            "monthly_limit": 2000,
        },
    }
    return client.post("/agents", json=payload).json()


def _run_task_until_terminal(client: TestClient, task_id: str) -> dict:
    task = None
    for _ in range(20):
        time.sleep(0.25)
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in ("BLOCKED", "COMPLETED", "FAILED", "AWAITING_APPROVAL", "VOIDED"):
            break
    return task


@pytest.mark.parametrize("query", [
    "team management software SaaS",
    "project management software unlimited users $99",
    "analytics dashboard subscription",
    "cloud hosting plan",
    "API access license",
])
def test_looks_like_non_physical_query_catches_real_observed_cases(query):
    assert orchestrator._looks_like_non_physical_query(query) is True


def test_looks_like_non_physical_query_does_not_flag_genuine_physical_goods():
    assert orchestrator._looks_like_non_physical_query("USB podcast microphone") is False
    assert orchestrator._looks_like_non_physical_query("standing desk converter") is False


def test_software_query_never_reaches_the_real_channel3_api(monkeypatch):
    """The exact real-world scenario: an agent asks Channel3 for software.
    The real search_products function must never even be called - the
    rejection has to happen before the network call, not just be a nicer
    error message after one."""
    calls = []

    async def fake_search_products(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("search_products should never be called for a software/SaaS query")

    monkeypatch.setattr(orchestrator, "search_products", fake_search_products)

    with TestClient(app) as client:
        agent = _saas_agent(client)

        search_attempt = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "channel3_search_products",
            {"query": "team management software SaaS"},
        )])
        proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_2", "create_purchase_proposal",
            {
                "merchant": "teamhub.com", "amount": 99.0, "currency": "USD",
                "category": "software", "reason": "Cheapest team management SaaS tool under $100",
                "source_url": "https://teamhub.com/99-dollar-deal/",
            },
        )])
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([search_attempt, proposal]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Renew our team management software"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        assert not calls, "the real Channel3 API was called for an obviously non-physical query"
        tx = task["transactions"][0]
        assert tx["merchant"] == "teamhub.com"

        event_types = [e["event_type"] for e in task["activity"]]
        assert "CHANNEL3_SEARCH_SKIPPED" in event_types
        assert "CHANNEL3_SEARCH_STARTED" not in event_types
        assert "CHANNEL3_SEARCH_COMPLETED" not in event_types


def test_genuinely_physical_query_still_reaches_channel3(monkeypatch):
    """Sanity check the other direction: a real physical-product task must
    not be caught by the same gate."""
    calls = []

    async def fake_search_products(query, max_price=None):
        calls.append(query)
        return [{
            "channel3_product_id": "p1", "title": "USB Podcast Microphone", "brand": "Blue",
            "category": "Microphones", "key_features": [], "image_url": None,
            "price": 59.99, "compare_at_price": None, "currency": "USD",
            "availability": "InStock", "retailer": "example.com",
            "buy_url": "https://example.com/mic", "offer_count": 1,
        }]

    monkeypatch.setattr(orchestrator, "search_products", fake_search_products)

    with TestClient(app) as client:
        agent = client.post("/agents", json={
            "name": "Office Supplies Agent",
            "purpose": "Buy office hardware",
            "directive": "Buy office hardware as needed, up to $150 autonomously.",
            "policy": {
                "max_transaction_amount": 150, "approval_threshold": 150,
                "daily_limit": 300, "monthly_limit": 2000,
            },
        }).json()

        search_call = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "channel3_search_products", {"query": "USB podcast microphone"},
        )])
        proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_2", "create_purchase_proposal",
            {
                "merchant": "example.com", "amount": 59.99, "currency": "USD",
                "category": "hardware", "reason": "Cheapest in-stock USB microphone",
                "source_url": "https://example.com/mic", "channel3_product_id": "p1",
            },
        )])
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([search_call, proposal]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Buy a USB podcast microphone"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        assert calls == ["USB podcast microphone"]
        event_types = [e["event_type"] for e in task["activity"]]
        assert "CHANNEL3_SEARCH_COMPLETED" in event_types
        assert "CHANNEL3_SEARCH_SKIPPED" not in event_types
