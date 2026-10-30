"""An agent must never act outside the purpose/directive it was delegated,
even when asked to. Two independent layers are supposed to guarantee this:

1. The agent itself should recognize a clearly unrelated task and call
   decline_out_of_scope_task instead of researching or proposing anything
   (soft, LLM-level; see app/agent/prompts.py).
2. Even if the agent ignores that and proposes something anyway, the
   deterministic policy engine's category allowlist must still block it
   (hard, deterministic; see app/guardrails/engine.py + rules.py). This is
   the layer that actually matters: it does not depend on the model
   behaving, only on the category it declares not matching the agent's
   allowed_categories.

Both are exercised here against the real orchestrator and policy engine,
with only the Groq network call itself faked out (no real API key or
network access is available in the test environment).
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


def _scoped_saas_agent(client: TestClient) -> dict:
    payload = {
        "name": "SaaS Agent",
        "purpose": "Manage SaaS subscriptions",
        "directive": "Only ever purchase software subscriptions for the team.",
        "policy": {
            "max_transaction_amount": 150,
            "approval_threshold": 100,
            "daily_limit": 300,
            "monthly_limit": 2000,
            "allowed_categories": ["software", "subscriptions"],
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


def test_agent_declines_task_outside_its_purpose(monkeypatch):
    """The agent calling decline_out_of_scope_task must end the task cleanly
    as BLOCKED, with no proposal or PayPal transaction ever created, and a
    distinct TASK_DECLINED_OUT_OF_SCOPE event recorded (not conflated with a
    real POLICY_BLOCKED decision, since the policy engine was never reached)."""
    with TestClient(app) as client:
        agent = _scoped_saas_agent(client)

        decline = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "decline_out_of_scope_task",
            {"reason": "Buying popcorn has no connection to managing SaaS subscriptions."},
        )])
        monkeypatch.setattr(orchestrator, "_groq_client", _fake_client_returning(decline))

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Buy a large popcorn for the office party"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        assert task["status"] == "BLOCKED"
        tx = task["transactions"][0]
        assert tx["decision"] == "BLOCK"
        assert tx["amount"] is None
        assert tx["merchant"] is None
        assert "popcorn" in tx["decision_reason"].lower() or "scope" in tx["decision_reason"].lower() \
            or "saas" in tx["decision_reason"].lower()

        event_types = [e["event_type"] for e in task["activity"]]
        assert "TASK_DECLINED_OUT_OF_SCOPE" in event_types
        assert "POLICY_EVALUATED" not in event_types
        assert "PROPOSAL_CREATED" not in event_types


def test_out_of_scope_proposal_still_blocked_even_if_agent_ignores_the_rule(monkeypatch):
    """Even if the agent does not decline and proposes an out-of-scope
    purchase anyway, the deterministic policy engine's category allowlist
    must still block it. This is the layer that must hold regardless of
    model behavior: it blocks by category, not by trusting the model."""
    with TestClient(app) as client:
        agent = _scoped_saas_agent(client)

        proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "create_purchase_proposal",
            {
                "merchant": "Snack Shop", "amount": 12.5, "currency": "USD",
                "category": "other", "reason": "Office party popcorn",
                "source_url": "https://example.com/popcorn",
            },
        )])
        monkeypatch.setattr(orchestrator, "_groq_client", _fake_client_returning(proposal))

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Buy popcorn for the office"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        assert task["status"] == "BLOCKED"
        tx = task["transactions"][0]
        assert tx["decision"] == "BLOCK"
        assert "category" in tx["decision_reason"].lower()
        assert tx["merchant"] == "Snack Shop"  # the proposal was real, just correctly rejected


def test_in_scope_proposal_is_allowed(monkeypatch):
    """Sanity check that scoping a policy to specific categories does not
    also break ordinary, genuinely in-scope purchases."""
    with TestClient(app) as client:
        agent = _scoped_saas_agent(client)

        proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "create_purchase_proposal",
            {
                "merchant": "Notion", "amount": 48.0, "currency": "USD",
                "category": "software", "reason": "Team project management subscription",
                "source_url": "https://notion.so/pricing",
            },
        )])
        monkeypatch.setattr(orchestrator, "_groq_client", _fake_client_returning(proposal))

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Renew our project management software"}
        ).json()
        task = _run_task_until_terminal(client, task["id"])

        tx = task["transactions"][0]
        assert tx["decision"] == "ALLOW"
