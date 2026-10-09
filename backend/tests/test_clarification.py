"""The agent's next turn can be plain conversational text instead of a tool
call - a clarifying question ("none of these match $1000, want this cheaper
one instead or should I keep searching?"), or any other check-in. That must
never be treated as a research failure that dead-ends the task into FAILED.
Instead the task pauses in NEEDS_INPUT with its exact conversation
preserved, a human replies via POST /tasks/{id}/respond, and the same loop
resumes with full context - potentially all the way through to a real
ALLOW/proposal, exercised end to end here with only the OpenRouter network
call faked out.
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
    """Returns one message per .create() call, advancing through a fixed
    sequence and then repeating the last one - so it works whether the test
    pulls N messages via one continuous loop or across a pause/resume split
    into two separate _run_research_loop invocations (and therefore two
    separate _openrouter_client() factory calls)."""

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


def test_clarifying_question_pauses_task_instead_of_failing(monkeypatch):
    """A plain conversational reply (no tool call) must land the task in
    NEEDS_INPUT with the question preserved, not FAILED."""
    with TestClient(app) as client:
        agent = _permissive_agent(client)
        question = (
            "None of these match a $1000 software plan exactly, but I found a "
            "Microsoft Office lifetime license for $39.99 - want that instead, "
            "or should I keep searching?"
        )
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([FakeMessage(content=question)]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find a $1000 software plan deal"}
        ).json()
        task = _poll_until(client, task["id"], {"NEEDS_INPUT", "FAILED", "COMPLETED"})

        assert task["status"] == "NEEDS_INPUT"
        tx = task["transactions"][0]
        assert tx["state"] == "NEEDS_INPUT"
        assert tx["pending_question"] == question
        assert tx["error"] is None

        event_types = [e["event_type"] for e in task["activity"]]
        assert "AGENT_ASKED_QUESTION" in event_types
        assert "TRANSACTION_FAILED" not in event_types


def test_replying_resumes_the_same_conversation_to_a_real_proposal(monkeypatch):
    """Once a human answers via POST /tasks/{id}/respond, the loop must
    resume with that reply appended to the real prior conversation and be
    able to reach an ordinary ALLOW decision, exactly as if the model had
    never needed to pause."""
    with TestClient(app) as client:
        agent = _permissive_agent(client)
        question = "Found a cheaper option outside your target price - proceed anyway?"
        proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "create_purchase_proposal",
            {
                "merchant": "StackSocial", "amount": 39.99, "currency": "USD",
                "category": "software", "reason": "Microsoft Office lifetime license, approved by user",
                "source_url": "https://stacksocial.com/office",
            },
        )])
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([FakeMessage(content=question), proposal]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find a $1000 software plan deal"}
        ).json()
        task = _poll_until(client, task["id"], {"NEEDS_INPUT", "FAILED"})
        assert task["status"] == "NEEDS_INPUT"

        resp = client.post(f"/tasks/{task['id']}/respond", json={"message": "Yes, go ahead with that one."})
        assert resp.status_code == 200

        # Stop as soon as the policy decision is in, same as the existing
        # scope tests: what happens after ALLOW (a real PayPal sandbox call)
        # is outside what this test is about, and must not make this test's
        # outcome depend on external network/credential state.
        task = _poll_until(client, task["id"], {"COMPLETED", "FAILED", "BLOCKED", "AWAITING_APPROVAL", "EXECUTING"})
        tx = task["transactions"][0]
        assert tx["merchant"] == "StackSocial"
        assert tx["decision"] == "ALLOW"

        event_types = [e["event_type"] for e in task["activity"]]
        assert "USER_REPLIED" in event_types
        reply_event = next(e for e in task["activity"] if e["event_type"] == "USER_REPLIED")
        assert reply_event["message"] == "Yes, go ahead with that one."


def test_cannot_reply_to_a_task_that_is_not_waiting_for_input(monkeypatch):
    with TestClient(app) as client:
        agent = _permissive_agent(client)
        proposal = FakeMessage(tool_calls=[FakeToolCall(
            "call_1", "create_purchase_proposal",
            {
                "merchant": "Notion", "amount": 48.0, "currency": "USD",
                "category": "software", "reason": "Subscription renewal",
                "source_url": "https://notion.so/pricing",
            },
        )])
        monkeypatch.setattr(orchestrator, "_openrouter_client", _fake_client_sequence([proposal]))

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Renew our project management software"}
        ).json()
        task = _poll_until(client, task["id"], {"COMPLETED", "FAILED", "BLOCKED"})
        assert task["status"] != "NEEDS_INPUT"

        resp = client.post(f"/tasks/{task['id']}/respond", json={"message": "anything"})
        assert resp.status_code == 400


def test_endless_clarifying_questions_eventually_fail_instead_of_looping_forever(monkeypatch):
    """A model stuck asking questions forever must not keep a task alive
    indefinitely - past MAX_CLARIFICATION_ROUNDS it should fail outright."""
    with TestClient(app) as client:
        agent = _permissive_agent(client)
        monkeypatch.setattr(
            orchestrator, "_openrouter_client",
            _fake_client_sequence([FakeMessage(content="Could you clarify your budget again?")]),
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find me something nice"}
        ).json()
        task_id = task["id"]

        for _ in range(orchestrator.MAX_CLARIFICATION_ROUNDS):
            task = _poll_until(client, task_id, {"NEEDS_INPUT", "FAILED"})
            if task["status"] == "FAILED":
                break
            client.post(f"/tasks/{task_id}/respond", json={"message": "Still not sure, you decide."})

        task = _poll_until(client, task_id, {"FAILED"})
        assert task["status"] == "FAILED"
        tx = task["transactions"][0]
        assert tx["state"] == "FAILED"
        assert "follow-up questions" in tx["error"]
