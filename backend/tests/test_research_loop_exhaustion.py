"""Real, observed failure: given an open-ended task ("find me the cheapest
management software for $200"), a model can keep re-searching for an even
better price round after round, never calling create_purchase_proposal,
and burn through the entire MAX_TOOL_ITERATIONS budget with real research
already done but nothing ever submitted. The task then failed with a
generic "Agent exceeded maximum reasoning steps without producing a
proposal." and the human got nothing - not even the real options the agent
had already found.

The fix: the LAST available call removes the research tools from the
schema entirely and forces tool_choice onto exactly
{create_purchase_proposal, decline_out_of_scope_task}, so a model that
would otherwise search forever is left with no option but to commit to its
best real finding or explicitly decline - never silent, resultless failure
after real work already happened.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.agent.orchestrator as orchestrator
from app.agent.orchestrator import MAX_TOOL_ITERATIONS
from app.agent.tools import build_terminal_tool_schemas
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


class _RecordingCompletions:
    """Returns a never-ending search_web tool call UNLESS this particular
    request forced tool_choice="required" (the hard-stop final call), in
    which case it plays the part of a cooperative model that commits to a
    real proposal once research is no longer an option. Every call's
    kwargs are recorded so the test can inspect exactly what the
    orchestrator asked for on the final round."""

    def __init__(self):
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("tool_choice") == "required":
            msg = FakeMessage(tool_calls=[FakeToolCall(
                f"call_{len(self.calls)}", "create_purchase_proposal",
                {
                    "merchant": "TeamHub", "amount": 180.0, "currency": "USD",
                    "category": "software",
                    "reason": "Cheapest real option found across all searches so far.",
                    "source_url": "https://teamhub.com/blog/cheapest-project-management-software/",
                },
            )])
        else:
            msg = FakeMessage(tool_calls=[FakeToolCall(
                f"call_{len(self.calls)}", "search_web",
                {"query": "even cheaper management software"},
            )])
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _fake_client_factory():
    completions = _RecordingCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return (lambda: client), completions


async def _fake_search_web(query: str):
    return [{"title": "Some result", "url": "https://example.com", "snippet": "A real-looking snippet."}]


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
    for _ in range(30):
        time.sleep(0.2)
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in statuses:
            break
    return task


def test_build_terminal_tool_schemas_only_has_the_two_concluding_tools():
    schemas = build_terminal_tool_schemas(["software", "subscriptions", "other"])
    names = {s["function"]["name"] for s in schemas}
    assert names == {"create_purchase_proposal", "decline_out_of_scope_task"}
    category_prop = next(
        s for s in schemas if s["function"]["name"] == "create_purchase_proposal"
    )["function"]["parameters"]["properties"]["category"]
    assert category_prop["enum"] == ["software", "subscriptions", "other"]


def test_endlessly_searching_model_is_forced_to_commit_on_the_final_call(monkeypatch):
    """Reproduces the exact live failure (a model that keeps searching for
    a cheaper price and never proposes) and proves the hard stop rescues
    it: a task that used to FAIL with zero result now completes with the
    real option the model had already found."""
    fake_client_fn, completions = _fake_client_factory()
    monkeypatch.setattr(orchestrator, "_groq_client", fake_client_fn)
    monkeypatch.setattr(orchestrator, "search_web", _fake_search_web)

    with TestClient(app) as client:
        agent = _permissive_agent(client)
        task = client.post(
            "/tasks",
            json={"agent_id": agent["id"], "prompt": "find me the cheapest management software for 200 dollars"},
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "EXECUTING", "AWAITING_APPROVAL"})

    # The old bug: this ended in FAILED with "Agent exceeded maximum
    # reasoning steps without producing a proposal." and no transaction
    # detail at all, despite real search results already being in hand.
    # (The test sandbox has no real PayPal credentials, so a FAILED status
    # here can legitimately mean "PayPal isn't configured" rather than a
    # regression - what actually matters is that the research loop itself
    # produced a real proposal instead of dying with the old message.)
    tx = task["transactions"][0]
    assert tx.get("error") != "Agent exceeded maximum reasoning steps without producing a proposal."
    assert tx["merchant"] == "TeamHub"
    assert tx["amount"] == 180.0

    # Exactly MAX_TOOL_ITERATIONS calls were made (it never found a reason
    # to stop early - that's the point, it was simulating a model that
    # genuinely never would), and the very last one is the forced one.
    assert len(completions.calls) == MAX_TOOL_ITERATIONS
    final_call = completions.calls[-1]
    assert final_call["tool_choice"] == "required"
    final_tool_names = {s["function"]["name"] for s in final_call["tools"]}
    assert final_tool_names == {"create_purchase_proposal", "decline_out_of_scope_task"}

    # Every call before the last one still had the full research toolkit
    # available and wasn't forced - the model is only ever cornered on the
    # genuinely last call, never before.
    for earlier_call in completions.calls[:-1]:
        assert earlier_call["tool_choice"] == "auto"
        assert len(earlier_call["tools"]) > 2


def test_stubborn_model_that_still_cant_commit_on_the_final_call_pauses_for_input(monkeypatch):
    """Even the forced final call can fail to land a real result - e.g. a
    model that only ever proposes an invalid/hallucinated product and never
    once calls decline_out_of_scope_task either. Before this fix, that dead
    end FAILED the whole task outright with a generic "try again" message,
    throwing away everything already researched and forcing the human to
    retype the entire request in a brand new task. It should instead pause
    in NEEDS_INPUT with the real conversation preserved, exactly like every
    other "genuinely stuck" dead end in this loop, so a reply in the same
    task can pick research back up with full context."""

    class _NeverCommits:
        def __init__(self):
            self.calls = 0

        async def create(self, **kwargs):
            self.calls += 1
            # Always an invalid tool call (missing every required field),
            # regardless of whether research tools or only the terminal
            # ones are on offer - this model cannot ever produce a usable
            # proposal or an explicit decline.
            msg = FakeMessage(tool_calls=[FakeToolCall(
                f"call_{self.calls}", "create_purchase_proposal", {},
            )])
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    completions = _NeverCommits()
    monkeypatch.setattr(orchestrator, "_groq_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    ))
    monkeypatch.setattr(orchestrator, "search_web", _fake_search_web)

    with TestClient(app) as client:
        agent = _permissive_agent(client)
        task = client.post(
            "/tasks",
            json={"agent_id": agent["id"], "prompt": "find me the cheapest management software"},
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "NEEDS_INPUT"})

    assert task["status"] == "NEEDS_INPUT"
    tx = task["transactions"][0]
    assert tx["state"] == "NEEDS_INPUT"
    assert tx["pending_question"]
    assert "specific" in tx["pending_question"].lower() or "price range" in tx["pending_question"].lower()
