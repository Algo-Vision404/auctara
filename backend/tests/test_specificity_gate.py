"""The agent's main SYSTEM_PROMPT already told it to ask for a product/use
case and a budget before researching a vague task like "buy me a software" -
in practice, tested live against the actual free-tier model this platform
runs, it did not reliably follow that instruction and just started
searching anyway. A nuanced instruction competing with many others deep in
a long system prompt, applied on the model's own initiative mid-conversation,
is not something a weak model can be trusted to always get right.

_check_task_specificity is the fix: a separate, narrow, FORCED tool call
whose only job is this one yes/no decision, run once before a brand-new
task is ever allowed into the real (expensive, multi-step) research loop.
These tests cover it directly (mocking the Groq response) and cover
its wiring into the real run_task/resume_task pipeline.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.agent.orchestrator as orchestrator
from app.agent.orchestrator import _check_task_specificity as _real_check_task_specificity
from app.database import models
from app.main import app


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict):
        self.id = call_id
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments))


def _fake_specificity_response(monkeypatch, *, names_product_or_use: bool, states_budget: bool,
                                 clarifying_question: str = ""):
    """Patches _groq_client so the one call _check_task_specificity
    makes returns a canned specificity_check tool call, without touching
    anything _run_research_loop itself would use."""
    call_args = {
        "names_product_or_use": names_product_or_use,
        "states_budget": states_budget,
        "clarifying_question": clarifying_question,
    }

    class FakeMessage:
        tool_calls = [FakeToolCall("call_1", "specificity_check", call_args)]

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(choices=[FakeChoice()])

    class FakeChatAPI:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChatAPI()

    monkeypatch.setattr(orchestrator, "_groq_client", lambda: FakeClient())


def _agent(client: TestClient) -> dict:
    payload = {
        "name": "Shopping Agent",
        "purpose": "Buy software and digital subscriptions the user asks for.",
        "directive": "Research the best real option and buy it within budget.",
        "policy": {
            "max_transaction_amount": 200, "approval_threshold": 150,
            "daily_limit": 500, "monthly_limit": 3000, "allowed_categories": [],
        },
    }
    return client.post("/agents", json=payload).json()


def _poll_until(client: TestClient, task_id: str, statuses: set[str]) -> dict:
    task = None
    for _ in range(25):
        time.sleep(0.2)
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in statuses:
            break
    return task


# ------------------------------------------------- _check_task_specificity --
async def test_names_product_and_budget_passes(monkeypatch):
    _fake_specificity_response(monkeypatch, names_product_or_use=True, states_budget=True)
    question = await _real_check_task_specificity("buy me Microsoft Office for $50")
    assert question is None


async def test_missing_product_asks_a_question(monkeypatch):
    _fake_specificity_response(
        monkeypatch, names_product_or_use=False, states_budget=True,
        clarifying_question="What kind of software would you like me to buy?",
    )
    question = await _real_check_task_specificity("buy me $50 of software")
    assert question == "What kind of software would you like me to buy?"


async def test_missing_budget_asks_a_question(monkeypatch):
    _fake_specificity_response(
        monkeypatch, names_product_or_use=True, states_budget=False,
        clarifying_question="How much would you like to spend on Microsoft Office?",
    )
    question = await _real_check_task_specificity("buy me Microsoft Office")
    assert question == "How much would you like to spend on Microsoft Office?"


async def test_missing_both_still_asks_even_without_a_model_supplied_question(monkeypatch):
    """A weak model might set both booleans false but leave the question
    field blank - must still produce a usable question, not an empty pause."""
    _fake_specificity_response(monkeypatch, names_product_or_use=False, states_budget=False,
                                 clarifying_question="")
    question = await _real_check_task_specificity("buy me a software")
    assert question
    assert "product" in question.lower() or "spend" in question.lower()


async def test_provider_failure_fails_open_not_blocking_the_task(monkeypatch):
    """If the gate itself cannot get an answer (provider outage, bad
    response shape), it must never permanently block every task behind a
    broken check - fail open and let the real research loop's own
    "genuinely stuck" ask be the fallback instead."""
    def _broken_client():
        raise RuntimeError("simulated Groq outage")

    monkeypatch.setattr(orchestrator, "_groq_client", _broken_client)
    question = await _real_check_task_specificity("buy me a software")
    assert question is None


# ------------------------------------------------------------- wiring tests --
def test_vague_task_pauses_for_clarification_before_any_research(monkeypatch):
    """End-to-end through the real POST /tasks -> run_task path: a task the
    gate flags as too vague must pause in NEEDS_INPUT with the gate's exact
    question, and _run_research_loop must never even be called - proving
    the gate genuinely short-circuits research rather than running
    alongside it."""
    with TestClient(app) as client:
        agent = _agent(client)

        research_loop_calls = []

        async def _fake_research_loop(agent_, task_, tx_id_, messages_, categories_):
            research_loop_calls.append(1)
            raise AssertionError("must not reach the research loop for a too-vague task")

        monkeypatch.setattr(orchestrator, "_run_research_loop", _fake_research_loop)
        monkeypatch.setattr(
            orchestrator, "_check_task_specificity",
            lambda task_prompt: _coro("What kind of product or service would you like?"),
        )

        task = client.post("/tasks", json={"agent_id": agent["id"], "prompt": "buy me a software"}).json()
        task = _poll_until(client, task["id"], {"NEEDS_INPUT", "FAILED", "COMPLETED", "BLOCKED"})

        assert task["status"] == "NEEDS_INPUT"
        assert research_loop_calls == []
        tx = task["transactions"][0]
        assert tx["pending_question"] == "What kind of product or service would you like?"


def test_specific_enough_task_proceeds_straight_to_research(monkeypatch):
    """The converse: a task the gate approves must flow straight into the
    real research loop with no pause at all."""
    with TestClient(app) as client:
        agent = _agent(client)

        async def _fake_research_loop(agent_, task_, tx_id_, messages_, categories_):
            return {
                "merchant": "Microsoft", "amount": 49.97, "currency": "USD",
                "category": "software", "reason": "Best option found.",
                "source_url": "https://example.com",
            }

        monkeypatch.setattr(orchestrator, "_run_research_loop", _fake_research_loop)
        monkeypatch.setattr(orchestrator, "_check_task_specificity", lambda task_prompt: _coro(None))

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "buy me Microsoft Office for $50"}
        ).json()
        task = _poll_until(client, task["id"], {"COMPLETED", "FAILED", "BLOCKED", "NEEDS_INPUT"})

        assert task["status"] != "NEEDS_INPUT"
        tx = task["transactions"][0]
        assert tx["merchant"] == "Microsoft"


def test_resuming_after_a_reply_does_not_re_run_the_gate(monkeypatch):
    """resume_task must go straight to the research loop - the gate only
    ever runs once, on a brand-new task. If it ran again on resume and the
    model's canned answer still said "not specific enough", a real user
    reply that actually supplied the missing details would wrongly loop
    back into another question instead of proceeding."""
    with TestClient(app) as client:
        agent = _agent(client)

        async def _fake_research_loop(agent_, task_, tx_id_, messages_, categories_):
            return {
                "merchant": "Microsoft", "amount": 49.97, "currency": "USD",
                "category": "software", "reason": "Best option found.",
                "source_url": "https://example.com",
            }

        monkeypatch.setattr(orchestrator, "_run_research_loop", _fake_research_loop)

        gate_calls = []

        def _gate(task_prompt):
            gate_calls.append(task_prompt)
            return _coro("What kind of product or service would you like?")

        monkeypatch.setattr(orchestrator, "_check_task_specificity", _gate)

        task = client.post("/tasks", json={"agent_id": agent["id"], "prompt": "buy me a software"}).json()
        task = _poll_until(client, task["id"], {"NEEDS_INPUT"})
        assert task["status"] == "NEEDS_INPUT"
        assert len(gate_calls) == 1

        reply = client.post(f"/tasks/{task['id']}/respond", json={"message": "Microsoft Office, up to $50"})
        assert reply.status_code == 200
        task = _poll_until(client, task["id"], {"COMPLETED", "FAILED", "BLOCKED", "NEEDS_INPUT"})

        assert task["status"] != "NEEDS_INPUT"
        assert len(gate_calls) == 1, "the gate must not run again on resume"


async def _coro(value):
    return value
