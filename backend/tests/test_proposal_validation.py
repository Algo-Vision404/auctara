"""A purchase proposal with a $0.00 (or negative) amount must never reach
PayPal. Before this fix, `args[f] in (None, "")` does not catch 0 or 0.0, so
a bogus/unfound price sailed past the missing-field check, through policy
evaluation (trivially within any budget), all the way to PayPal - which
correctly rejects a zero-amount order, but only after the task already
looked proposed and ALLOWED to the user, with a confusing raw PayPal error
as the only explanation. Two independent layers now guard against this:

1. The create_purchase_proposal tool handler itself rejects a non-positive
   amount and bounces it back to the agent as a tool error (soft, gives the
   model a chance to self-correct or ask the user).
2. A deterministic backstop in _continue_research refuses to let any
   non-positive amount reach policy evaluation, regardless of how it got
   there (hard, does not depend on the model behaving).
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


def _zero_amount_proposal(merchant="Baremetrics", amount=0.0):
    return FakeMessage(tool_calls=[FakeToolCall(
        "call_1", "create_purchase_proposal",
        {
            "merchant": merchant, "amount": amount, "currency": "USD",
            "category": "software", "reason": "Best overall pick for subscription analytics software.",
            "source_url": "https://worldmetrics.org/best/subscription-analytics-software/",
        },
    )])


def test_zero_amount_proposal_is_rejected_and_never_reaches_paypal(monkeypatch):
    """A stubborn $0.00 proposal that the model never corrects must end the
    task in FAILED with a clear reason, never create a PayPal order, and
    never report ALLOW (there is nothing real to allow)."""
    with TestClient(app) as client:
        agent = _permissive_agent(client)
        # The model proposes $0.00 every single time, never self-correcting -
        # exercises both the tool bounce-back AND the eventual max-iterations
        # dead end, while proving no PayPal call is ever attempted.
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([_zero_amount_proposal()] * 10),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED"})

        assert task["status"] == "FAILED"
        tx = task["transactions"][0]
        assert tx["state"] == "FAILED"
        assert tx["decision"] is None  # never reached policy evaluation
        assert tx["paypal_order_id"] is None  # never reached PayPal

        event_types = [e["event_type"] for e in task["activity"]]
        assert "POLICY_EVALUATED" not in event_types
        assert "PAYPAL_ORDER_CREATED" not in event_types


def test_agent_can_self_correct_after_zero_amount_is_rejected(monkeypatch):
    """If the model proposes $0.00 once but then proposes a real price after
    seeing the tool error, the task should succeed normally - the bounce-back
    is a nudge to retry, not an automatic failure."""
    with TestClient(app) as client:
        agent = _permissive_agent(client)
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
            _fake_client_sequence([_zero_amount_proposal(), real_proposal]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "EXECUTING"})

        tx = task["transactions"][0]
        assert tx["merchant"] == "Baremetrics"
        assert tx["amount"] == 129.0
        assert tx["decision"] == "ALLOW"


def test_negative_amount_proposal_is_also_rejected(monkeypatch):
    with TestClient(app) as client:
        agent = _permissive_agent(client)
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([_zero_amount_proposal(amount=-10.0)] * 10),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED"})

        assert task["status"] == "FAILED"
        tx = task["transactions"][0]
        assert tx["paypal_order_id"] is None


def test_deterministic_backstop_catches_zero_amount_even_if_tool_check_is_bypassed(monkeypatch):
    """Defense in depth: even if a $0 proposal somehow made it out of
    _run_research_loop (bypassing its own tool-call validation entirely),
    _continue_research's own check must still refuse to let it reach policy
    evaluation or PayPal."""
    with TestClient(app) as client:
        agent = _permissive_agent(client)

        async def _fake_research_loop(agent_, task_, tx_id_, messages_, categories_):
            return {
                "merchant": "Baremetrics", "amount": 0.0, "currency": "USD",
                "category": "software", "reason": "bypassed validation",
                "source_url": "https://example.com",
            }

        monkeypatch.setattr(orchestrator, "_run_research_loop", _fake_research_loop)

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED"})

        assert task["status"] == "FAILED"
        tx = task["transactions"][0]
        assert tx["decision"] is None
        assert tx["paypal_order_id"] is None
        assert "not a real, positive" in tx["error"]
