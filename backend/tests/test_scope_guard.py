"""The independent scope guard (app.agent.scope_guard.check_scope) is a
second, separate model call - its own fresh conversation, no access to the
research loop's own context - that judges a FINISHED proposal against the
agent's own stated purpose/directive, as a backend-enforced check instead of
relying solely on the research-loop model self-reporting via
decline_out_of_scope_task (see test_agent_scope.py for that softer layer,
and the deterministic category-allowlist layer it already has).

Confirmed product behavior this guard must implement:
  - Disagreement (or an inability to even run the check) never hard-blocks
    on its own: it only ever escalates an otherwise-ALLOW decision to
    AWAITING_APPROVAL, so a human makes the final call instead of the guard
    silently overriding anything.
  - A decision that was already going to be BLOCK is left alone - skipped
    entirely, since BLOCK is already the strictest possible outcome and
    there is nothing a scope opinion could add. (The scope guard also must
    not spend an extra LLM call checking a transaction that is already
    being blocked.)
  - A decision that was already APPROVAL_REQUIRED stays APPROVAL_REQUIRED,
    but still picks up the scope note in its reason so a human reviewing it
    sees the full picture.
  - Agreement (in_scope=True) leaves the original decision completely
    unaffected.
  - A check that raises/fails to produce a verdict is fail-closed: treated
    exactly like a disagreement, never as a silent pass.

The research loop itself is stubbed out directly (monkeypatching
orchestrator._run_research_loop, same pattern as
test_policy_decision_safety_net.py) so each test only has to say what
proposal came out of research and what the independent scope check should
report - the real policy engine and the real new override logic in
orchestrator._continue_research run unmodified.
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

import app.agent.orchestrator as orchestrator
from app.agent.scope_guard import ScopeVerdict
from app.main import app


def _saas_agent(client: TestClient, **policy_overrides) -> dict:
    policy = {
        "max_transaction_amount": 500,
        "approval_threshold": 200,
        "daily_limit": 1000,
        "monthly_limit": 5000,
        "allowed_categories": ["software", "subscriptions"],
    }
    policy.update(policy_overrides)
    payload = {
        "name": "SaaS Agent",
        "purpose": "Manage SaaS subscriptions",
        "directive": "Only ever purchase software subscriptions for the team.",
        "policy": policy,
    }
    return client.post("/agents", json=payload).json()


def _stub_research_loop(monkeypatch, proposal: dict) -> None:
    async def _fake(agent_, task_, tx_id_, messages_, categories_):
        return proposal

    monkeypatch.setattr(orchestrator, "_run_research_loop", _fake)


def _stub_scope_check(monkeypatch, *, ok: bool, in_scope: bool, reason: str = "stub") -> None:
    async def _fake(*args, **kwargs):
        return ScopeVerdict(ok=ok, in_scope=in_scope, reason=reason)

    monkeypatch.setattr(orchestrator, "check_scope", _fake)


def _poll_until(client: TestClient, task_id: str, statuses: set[str]) -> dict:
    task = None
    for _ in range(25):
        time.sleep(0.2)
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in statuses:
            break
    return task


def _cheap_in_scope_proposal() -> dict:
    return {
        "merchant": "Notion", "amount": 48.0, "currency": "USD",
        "category": "software", "reason": "Team project management subscription",
        "source_url": "https://notion.so/pricing",
    }


def test_scope_agreement_leaves_allow_untouched(monkeypatch):
    with TestClient(app) as client:
        agent = _saas_agent(client)
        _stub_research_loop(monkeypatch, _cheap_in_scope_proposal())
        _stub_scope_check(monkeypatch, ok=True, in_scope=True, reason="Plausibly software.")

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Renew our project management software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "AWAITING_APPROVAL", "EXECUTING"})

        tx = task["transactions"][0]
        assert tx["decision"] == "ALLOW"
        event_types = [e["event_type"] for e in task["activity"]]
        assert "SCOPE_CHECKED" in event_types


def test_scope_disagreement_downgrades_allow_to_approval_required(monkeypatch):
    """A proposal that policy alone would have auto-approved (within
    autonomous authority) must be escalated to a human when the independent
    scope check disagrees, per the user-confirmed "never hard-block, always
    let a human make the final call" behavior."""
    with TestClient(app) as client:
        agent = _saas_agent(client)
        # $48 is comfortably under both the $200 approval_threshold and the
        # $500 max_transaction_amount, so policy alone would ALLOW this.
        _stub_research_loop(monkeypatch, _cheap_in_scope_proposal())
        _stub_scope_check(
            monkeypatch, ok=True, in_scope=False,
            reason="This looks like a personal purchase, not a team SaaS subscription.",
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Renew our project management software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "AWAITING_APPROVAL", "EXECUTING"})

        assert task["status"] == "AWAITING_APPROVAL"
        tx = task["transactions"][0]
        assert tx["decision"] == "APPROVAL_REQUIRED"
        assert "scope" in tx["decision_reason"].lower()
        assert "personal purchase" in tx["decision_reason"].lower()


def test_scope_check_failure_fails_closed_to_approval_required(monkeypatch):
    """If the independent check itself cannot run (provider error, timeout,
    malformed response), that must never be silently treated as a pass -
    the user-confirmed fail-closed behavior."""
    with TestClient(app) as client:
        agent = _saas_agent(client)
        _stub_research_loop(monkeypatch, _cheap_in_scope_proposal())
        _stub_scope_check(
            monkeypatch, ok=False, in_scope=False,
            reason="The independent scope check could not be completed.",
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Renew our project management software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "AWAITING_APPROVAL", "EXECUTING"})

        assert task["status"] == "AWAITING_APPROVAL"
        tx = task["transactions"][0]
        assert tx["decision"] == "APPROVAL_REQUIRED"
        assert "could not be completed" in tx["decision_reason"].lower()


def test_scope_disagreement_does_not_override_an_existing_block(monkeypatch):
    """A proposal already BLOCKed by the deterministic category allowlist
    must stay BLOCKed - the scope guard only ever escalates ALLOW, it never
    "un-blocks" or otherwise touches a decision that was already the
    strictest outcome. The check must also be skipped entirely here (no
    wasted LLM call on an already-blocked transaction)."""
    with TestClient(app) as client:
        agent = _saas_agent(client)
        out_of_category_proposal = {
            "merchant": "Snack Shop", "amount": 12.5, "currency": "USD",
            "category": "other", "reason": "Office party popcorn",
            "source_url": "https://example.com/popcorn",
        }
        _stub_research_loop(monkeypatch, out_of_category_proposal)

        calls = []

        async def _fail_if_called(*args, **kwargs):
            calls.append(1)
            return ScopeVerdict(ok=True, in_scope=False, reason="should never run")

        monkeypatch.setattr(orchestrator, "check_scope", _fail_if_called)

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Buy popcorn for the office"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "AWAITING_APPROVAL", "EXECUTING"})

        assert task["status"] == "BLOCKED"
        tx = task["transactions"][0]
        assert tx["decision"] == "BLOCK"
        assert calls == [], "scope guard must not be invoked for a proposal already BLOCKed by policy"


def test_scope_disagreement_on_already_approval_required_adds_note_but_keeps_decision(monkeypatch):
    """A proposal already requiring human approval purely on dollar amount
    must stay APPROVAL_REQUIRED either way - a human was already going to
    review it - but the scope guard's concern should still be visible in
    the reason a reviewer reads."""
    with TestClient(app) as client:
        agent = _saas_agent(client)  # approval_threshold=200
        pricier_proposal = {
            "merchant": "Notion", "amount": 350.0, "currency": "USD",
            "category": "software", "reason": "Annual team plan",
            "source_url": "https://notion.so/pricing",
        }
        _stub_research_loop(monkeypatch, pricier_proposal)
        _stub_scope_check(
            monkeypatch, ok=True, in_scope=False,
            reason="Annual commitment seems outside the agent's narrow directive.",
        )

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Get us the annual plan"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED", "AWAITING_APPROVAL", "EXECUTING"})

        assert task["status"] == "AWAITING_APPROVAL"
        tx = task["transactions"][0]
        assert tx["decision"] == "APPROVAL_REQUIRED"
        assert "annual commitment" in tx["decision_reason"].lower()
