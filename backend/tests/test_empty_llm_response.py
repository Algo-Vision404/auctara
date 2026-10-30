"""Real, observed failure: a free-tier model occasionally
returns a normal 200 OK with `choices` set to None (or an empty list) -
no exception, no error status, nothing indicating a problem. Every call
site that read `response.choices[0]` directly crashed with a raw
`TypeError: 'NoneType' object is not subscriptable`, which propagated out
as a generic "something unexpected went wrong" failure - a bug in how this
app handled an ordinary provider hiccup, not an actual error in the task
itself.

app.agent.llm_errors.require_first_choice + the EmptyLLMResponseError it
raises close this gap: the empty-response case is now classified as
transient (see is_transient_llm_error) and gets the same short retried-
with-backoff treatment as a 429 or a 5xx, from inside the exact callable
passed to call_llm_with_retry so a retry actually re-issues the request
instead of re-reading the same empty response.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.agent.orchestrator as orchestrator
from app.agent.llm_errors import EmptyLLMResponseError, is_transient_llm_error, require_first_choice
from app.main import app


def test_require_first_choice_returns_the_real_choice_when_present():
    msg = SimpleNamespace(content="hello")
    response = SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    assert require_first_choice(response).message is msg


@pytest.mark.parametrize("bad_choices", [None, []])
def test_require_first_choice_raises_instead_of_crashing_on_empty_choices(bad_choices):
    response = SimpleNamespace(choices=bad_choices)
    with pytest.raises(EmptyLLMResponseError):
        require_first_choice(response)


def test_empty_llm_response_error_is_treated_as_transient():
    assert is_transient_llm_error(EmptyLLMResponseError("no choices")) is True


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


class _FlakyThenGoodCompletions:
    """Simulates the real observed failure: the first `fail_times` calls
    come back as a 200 OK with no choices at all, then a real, usable
    proposal on the next call - proving a transient empty response gets
    retried and recovered from, rather than failing the whole task."""

    def __init__(self, fail_times: int, good_message: "FakeMessage"):
        self.fail_times = fail_times
        self.good_message = good_message
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            return SimpleNamespace(choices=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=self.good_message)])


class _AlwaysEmptyCompletions:
    """Simulates the provider being persistently broken for the whole
    retry budget - the one case that really should fail the task, just
    with a clean human-facing message instead of a raw crash."""

    async def create(self, **kwargs):
        return SimpleNamespace(choices=[])


def _fake_client(completions) -> callable:
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return lambda: client


def _permissive_agent(client: TestClient) -> dict:
    payload = {
        "name": "Shopping Agent",
        "purpose": "Find and buy software deals",
        "directive": "Find the best software plan deals for the team.",
        "policy": {
            "max_transaction_amount": 1500, "approval_threshold": 1500,
            "daily_limit": 3000, "monthly_limit": 10000, "allowed_categories": [],
        },
    }
    return client.post("/agents", json=payload).json()


def _poll_until(client: TestClient, task_id: str, statuses: set[str]) -> dict:
    task = None
    for _ in range(30):
        time.sleep(0.2)
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in statuses:
            break
    return task


def test_a_transient_empty_response_is_retried_and_the_task_still_completes(monkeypatch):
    proposal = FakeMessage(tool_calls=[FakeToolCall(
        "call_1", "create_purchase_proposal",
        {
            "merchant": "TeamHub", "amount": 180.0, "currency": "USD",
            "category": "software", "reason": "Best overall pick.",
            "source_url": "https://example.com",
        },
    )])
    # Fails twice (well under call_llm_with_retry's max_attempts), then
    # succeeds - the orchestrator must never see this as anything other
    # than a normal successful research loop.
    completions = _FlakyThenGoodCompletions(fail_times=2, good_message=proposal)
    monkeypatch.setattr(orchestrator, "_groq_client", _fake_client(completions))

    with TestClient(app) as client:
        agent = _permissive_agent(client)
        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "EXECUTING", "AWAITING_APPROVAL"})

    tx = task["transactions"][0]
    assert tx["merchant"] == "TeamHub"
    assert tx["amount"] == 180.0
    # Never a raw crash message, and a real proposal was reached despite
    # the first two calls coming back empty.
    assert tx.get("error") != "Something unexpected went wrong while this agent was working on the task."
    assert completions.calls == 3


def test_persistently_empty_responses_fail_cleanly_not_with_a_raw_crash(monkeypatch):
    completions = _AlwaysEmptyCompletions()
    monkeypatch.setattr(orchestrator, "_groq_client", _fake_client(completions))

    with TestClient(app) as client:
        agent = _permissive_agent(client)
        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED"})

    assert task["status"] == "FAILED"
    tx = task["transactions"][0]
    assert tx["state"] == "FAILED"
    # A real, human-readable message - never a bare Python exception
    # (TypeError/IndexError text) leaking onto the task.
    assert "TypeError" not in (tx["error"] or "")
    assert "NoneType" not in (tx["error"] or "")
