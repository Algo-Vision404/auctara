"""_continue_research's research-loop call was already wrapped in a
catch-all: any unexpected exception there cleanly fails the transaction
(releasing any reserved budget) instead of leaving it stranded. Everything
AFTER that loop succeeded - normalizing the proposed price, evaluating
policy (which reserves budget the instant it decides ALLOW or
APPROVAL_REQUIRED), and recording that decision - had no such net.

run_task is launched fire-and-forget via asyncio.create_task (both from
POST /tasks and the scheduler), so an unhandled exception anywhere in that
gap would never surface anywhere: the transaction would sit stuck in
PROPOSED/POLICY_CHECK/AUTHORIZED forever, and any budget already reserved
for it would never be released either. These tests prove that gap is now
closed, and that the fix does NOT also reach into execute_payment/
_finalize_payment, where a generic "just fail and release" response would
be actively wrong once PayPal has actually moved money.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.agent.orchestrator as orchestrator
from app.database import models
from app.database.database import get_connection
from app.main import app


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: dict):
        self.id = call_id
        self.type = "function"
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments))


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
    for _ in range(25):
        time.sleep(0.2)
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in statuses:
            break
    return task


def _valid_proposal():
    return {
        "merchant": "Baremetrics", "amount": 129.0, "currency": "USD",
        "category": "software", "reason": "Best overall pick for subscription analytics software.",
        "source_url": "https://example.com",
    }


def _net_reserved(agent_id: str) -> float:
    row = get_connection().execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM budget_ledger WHERE agent_id=?",
        (agent_id,),
    ).fetchone()
    return float(row["total"])


def test_crash_right_after_policy_reserves_budget_still_fails_cleanly(monkeypatch):
    """Simulates a bug/transient failure landing exactly where policy has
    already reserved budget for an ALLOW decision but nothing downstream
    has run yet - the real gap this fix closes."""
    with TestClient(app) as client:
        agent = _permissive_agent(client)

        async def _fake_research_loop(agent_, task_, tx_id_, messages_, categories_):
            return _valid_proposal()

        monkeypatch.setattr(orchestrator, "_run_research_loop", _fake_research_loop)

        real_evaluate = orchestrator._evaluate_policy_atomic

        def _evaluate_then_crash(*args, **kwargs):
            decision = real_evaluate(*args, **kwargs)  # actually reserves budget, like the real bug would see
            raise RuntimeError("simulated crash immediately after budget was reserved")

        monkeypatch.setattr(orchestrator, "_evaluate_policy_atomic", _evaluate_then_crash)

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED"})

        assert task["status"] == "FAILED"
        tx = task["transactions"][0]
        assert tx["state"] == "FAILED"
        assert "unexpected" in tx["error"].lower()
        assert _net_reserved(agent["id"]) == 0.0, (
            "budget reserved right before the crash must still be released, not left stranded"
        )


def test_crash_before_any_reservation_still_fails_cleanly_with_nothing_to_release(monkeypatch):
    """Same safety net, but for a crash earlier in the same block - before
    policy ever got a chance to reserve anything. Must still resolve to
    FAILED (not get stuck in PROPOSED forever) and must not fabricate a
    release against a reservation that never happened."""
    with TestClient(app) as client:
        agent = _permissive_agent(client)

        async def _fake_research_loop(agent_, task_, tx_id_, messages_, categories_):
            return _valid_proposal()

        monkeypatch.setattr(orchestrator, "_run_research_loop", _fake_research_loop)

        real_emit = orchestrator.emit

        async def _emit_then_crash(event_type, message, **kwargs):
            if event_type == "PROPOSAL_CREATED":
                raise RuntimeError("simulated crash recording the proposal, before policy ever ran")
            return await real_emit(event_type, message, **kwargs)

        monkeypatch.setattr(orchestrator, "emit", _emit_then_crash)

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED"})

        assert task["status"] == "FAILED"
        tx = task["transactions"][0]
        assert tx["decision"] is None  # never reached policy evaluation
        assert _net_reserved(agent["id"]) == 0.0


def test_safety_net_does_not_swallow_execute_payment_errors(monkeypatch):
    """execute_payment/_finalize_payment must keep handling their own
    failures (PayPalError -> _fail, with its own correct release/void
    logic) rather than having their exceptions caught by the new
    catch-all and blindly failed+released - that boundary matters because
    by the time execute_payment runs, real PayPal calls that can actually
    move money are in play."""
    with TestClient(app) as client:
        agent = _permissive_agent(client)

        async def _fake_research_loop(agent_, task_, tx_id_, messages_, categories_):
            return _valid_proposal()

        monkeypatch.setattr(orchestrator, "_run_research_loop", _fake_research_loop)

        from app.paypal.client import PayPalError

        async def _create_order_fails(*args, **kwargs):
            raise PayPalError("PayPal order creation failed: simulated upstream error")

        monkeypatch.setattr(orchestrator.paypal_orders, "create_order", _create_order_fails)

        task = client.post(
            "/tasks", json={"agent_id": agent["id"], "prompt": "Find subscription analytics software"}
        ).json()
        task = _poll_until(client, task["id"], {"FAILED", "COMPLETED", "BLOCKED"})

        assert task["status"] == "FAILED"
        tx = task["transactions"][0]
        # Reached execute_payment's own PayPalError handling specifically
        # (not the generic "something unexpected" message the new net
        # produces) - proof the two layers stayed properly separated.
        assert "PayPal order creation failed" in tx["error"]
        assert _net_reserved(agent["id"]) == 0.0
