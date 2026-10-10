"""create_purchase_proposal's channel3_product_id/image_url/retailer fields
are documented (see tools.py) as only ever belonging on a proposal "if this
candidate came from channel3_search_products" - but nothing used to check
that claim before this fix. The transaction detail page shows a confident
"Verified live listing" badge (ProposalSummary.tsx) directly off
tx.channel3_product_id being present, so a model fabricating one (or
carrying one over from an unrelated, rejected candidate - e.g. a t-shirt
id attached to a software proposal) would make that badge a lie with
nothing to ever catch it.

The fix cross-checks any claimed channel3_product_id against every id this
task's own channel3_search_products calls have actually returned, scanned
from the conversation's own tool-result messages (not a function-local
variable, which would not survive a NEEDS_INPUT pause/resume).

A second, narrower gap in the same spot: that check only looked at id
membership. Neither search_web (returns only {title, url, snippet}) nor
fetch_page (returns only stripped page text) ever produces an image_url or
a retailer-domain field anywhere in this codebase, so there is no
legitimate source for either field except Channel3 - meaning image_url/
retailer set with NO channel3_product_id at all has no legitimate
explanation, and a REAL channel3_product_id could still be paired with an
image_url/retailer/source_url copied from a different candidate's record
(or simply invented) without the id-only check ever noticing. Both are
covered below.
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


def _run_task_until_terminal(client: TestClient, task_id: str) -> dict:
    task = None
    for _ in range(20):
        time.sleep(0.25)
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in ("BLOCKED", "COMPLETED", "FAILED", "AWAITING_APPROVAL", "VOIDED"):
            break
    return task


def test_channel3_product_ids_seen_scans_messages_not_a_local_variable():
    products_payload = json.dumps({"products": [
        {"channel3_product_id": "real-1", "title": "A"},
        {"channel3_product_id": "real-2", "title": "B"},
    ]})
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "content": products_payload},
        {"role": "tool", "content": "not json at all"},
        {"role": "tool", "content": json.dumps({"results": ["no products key here"]})},
    ]
    assert orchestrator._channel3_product_ids_seen(messages) == {"real-1", "real-2"}


def test_fabricated_channel3_product_id_is_rejected(monkeypatch):
    """A model claiming a channel3_product_id that no real search in this
    task ever returned must be bounced back as a tool error, not allowed
    through to a transaction the UI would badge as a verified listing."""
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

        fabricated_proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "create_purchase_proposal",
            {
                "merchant": "example.com", "amount": 59.99, "currency": "USD",
                "category": "hardware", "reason": "Fabricated listing",
                "source_url": "https://example.com/mic",
                "channel3_product_id": "never-actually-returned",
                "image_url": "https://example.com/fake.jpg",
                "retailer": "example.com",
            },
        )])
        honest_retry = FakeMessage(tool_calls=[FakeToolCall(
            "call_2", "create_purchase_proposal",
            {
                "merchant": "example.com", "amount": 59.99, "currency": "USD",
                "category": "hardware", "reason": "Found via web search",
                "source_url": "https://example.com/mic",
            },
        )])
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([fabricated_proposal, honest_retry]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Buy a USB microphone"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        tx = task["transactions"][0]
        # The honest retry (no channel3_product_id) is what actually went through.
        assert tx["reason"] == "Found via web search"
        assert tx["channel3_product_id"] is None


def test_image_url_without_channel3_product_id_is_rejected(monkeypatch):
    """No tool other than channel3_search_products ever returns an image
    URL or a retailer domain, so either field attached without a matching,
    real channel3_product_id has no legitimate source at all - it can only
    have been invented. ProposalSummary.tsx renders tx.image_url as a real
    <img> with no badge gating it, unlike channel3_product_id's "Verified
    live listing" badge, so this would otherwise show a fabricated product
    photo with nothing marking it as unverified."""
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

        fabricated_image = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "create_purchase_proposal",
            {
                "merchant": "example.com", "amount": 59.99, "currency": "USD",
                "category": "hardware", "reason": "Found via web search",
                "source_url": "https://example.com/mic",
                "image_url": "https://example.com/invented-product-photo.jpg",
            },
        )])
        honest_retry = FakeMessage(tool_calls=[FakeToolCall(
            "call_2", "create_purchase_proposal",
            {
                "merchant": "example.com", "amount": 59.99, "currency": "USD",
                "category": "hardware", "reason": "Found via web search",
                "source_url": "https://example.com/mic",
            },
        )])
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([fabricated_image, honest_retry]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Buy a USB microphone"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        tx = task["transactions"][0]
        assert tx["reason"] == "Found via web search"
        assert tx["image_url"] is None


def test_channel3_fields_mismatched_with_the_claimed_product_are_rejected(monkeypatch):
    """A real channel3_product_id (one the task's own search actually
    returned) paired with an image_url/retailer/source_url lifted from a
    DIFFERENT candidate in the same result set must be rejected - the id
    being genuine is not enough, every Channel3-sourced field must belong
    to that exact product record."""
    async def fake_search_products(query, max_price=None):
        return [
            {
                "channel3_product_id": "cheap-1", "title": "Basic USB Microphone", "brand": "Acme",
                "category": "Microphones", "key_features": [], "image_url": "https://x/cheap.jpg",
                "price": 29.99, "compare_at_price": None, "currency": "USD",
                "availability": "InStock", "retailer": "cheapmart.com",
                "buy_url": "https://cheapmart.com/mic", "offer_count": 1,
            },
            {
                "channel3_product_id": "nice-2", "title": "Premium USB Microphone", "brand": "Blue",
                "category": "Microphones", "key_features": [], "image_url": "https://x/nice.jpg",
                "price": 89.99, "compare_at_price": None, "currency": "USD",
                "availability": "InStock", "retailer": "example.com",
                "buy_url": "https://example.com/nice-mic", "offer_count": 1,
            },
        ]

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
        # Real id ("cheap-1"), but the photo/retailer/link of the OTHER,
        # nicer-looking candidate - the exact mismatch the id-only check
        # could never catch.
        mismatched_proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_2", "create_purchase_proposal",
            {
                "merchant": "cheapmart.com", "amount": 29.99, "currency": "USD",
                "category": "hardware", "reason": "Cheapest in-stock option",
                "source_url": "https://example.com/nice-mic",
                "channel3_product_id": "cheap-1",
                "image_url": "https://x/nice.jpg", "retailer": "example.com",
            },
        )])
        honest_retry = FakeMessage(tool_calls=[FakeToolCall(
            "call_3", "create_purchase_proposal",
            {
                "merchant": "cheapmart.com", "amount": 29.99, "currency": "USD",
                "category": "hardware", "reason": "Cheapest in-stock option",
                "source_url": "https://cheapmart.com/mic",
                "channel3_product_id": "cheap-1",
                "image_url": "https://x/cheap.jpg", "retailer": "cheapmart.com",
            },
        )])
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([search_call, mismatched_proposal, honest_retry]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Buy a USB podcast microphone"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        tx = task["transactions"][0]
        # The honest, internally-consistent retry is what actually went through.
        assert tx["channel3_product_id"] == "cheap-1"
        assert tx["image_url"] == "https://x/cheap.jpg"
        assert tx["retailer"] == "cheapmart.com"
        assert tx["source_url"] == "https://cheapmart.com/mic"


def test_genuine_channel3_product_id_is_accepted(monkeypatch):
    """Sanity check the other direction: a real id the task's own Channel3
    search actually returned must still be accepted, not over-rejected."""
    async def fake_search_products(query, max_price=None):
        return [{
            "channel3_product_id": "p1", "title": "USB Podcast Microphone", "brand": "Blue",
            "category": "Microphones", "key_features": [], "image_url": "https://x/img.jpg",
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
                "image_url": "https://x/img.jpg", "retailer": "example.com",
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

        tx = task["transactions"][0]
        assert tx["channel3_product_id"] == "p1"
