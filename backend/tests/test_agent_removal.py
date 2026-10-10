"""Removing an agent (retire = soft, delete = hard) must:
  1. immediately stop it from accepting new tasks,
  2. cancel whatever it currently has in flight (CREATED here means we can
     force a transaction into a non-terminal state directly, simulating "a
     task is mid-flight right now"),
  3. for retire: keep its full history intact and visible,
  4. for delete: wipe the live agent/policy/task/transaction rows but leave
     the permanent audit trail (audit_records) untouched,
  5. never let a transaction that was cancelled resurrect itself if the
     original in-flight code path tries to keep writing to it afterward
     (the _set_tx_state compare-and-swap guard).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.agent.orchestrator as orchestrator
from app.agent.orchestrator import AgentError, _set_tx_state
from app.audit.integrity import list_audit
from app.database import models
from app.main import app
from app.state_machine import InvalidTransition


def _agent_payload():
    return {
        "name": "SaaS Agent",
        "purpose": "Manage our SaaS subscriptions",
        "directive": "Only ever purchase software subscriptions for the team.",
        "policy": {
            "max_transaction_amount": 150,
            "approval_threshold": 100,
            "daily_limit": 300,
            "monthly_limit": 2000,
            "allowed_categories": ["software", "subscriptions"],
        },
    }


def test_retiring_agent_blocks_new_tasks_but_keeps_history():
    with TestClient(app) as client:
        agent = client.post("/agents", json=_agent_payload()).json()

        # A real, already-completed-looking transaction in this agent's
        # history (we don't need the full pipeline here; a bare row created
        # directly via models is enough to assert it survives untouched).
        task = models.create_task(agent["id"], "Renew the team's project tracker", None, None)
        tx = models.create_transaction(task["id"], agent["id"])
        models.update_transaction(tx["id"], state="COMPLETED", decision="ALLOW",
                                   merchant="Notion", amount=48.0)

        resp = client.post(f"/agents/{agent['id']}/retire")
        assert resp.status_code == 200
        retired = resp.json()
        assert retired["status"] == "RETIRED"

        # New tasks are now rejected outright.
        blocked = client.post("/tasks", json={"agent_id": agent["id"], "prompt": "Renew Figma"})
        assert blocked.status_code == 400

        # Old history is untouched.
        fetched_agent = client.get(f"/agents/{agent['id']}").json()
        assert len(fetched_agent["transactions"]) == 1
        assert fetched_agent["transactions"][0]["state"] == "COMPLETED"
        assert fetched_agent["transactions"][0]["merchant"] == "Notion"


def test_retiring_agent_cancels_in_flight_task_and_releases_budget():
    with TestClient(app) as client:
        agent = client.post("/agents", json=_agent_payload()).json()

        # Simulate a task that is "awaiting human approval" right now: a
        # real reservation against the agent's budget, sitting in a
        # non-terminal state.
        task = models.create_task(agent["id"], "Renew the team's project tracker", None, None)
        tx = models.create_transaction(task["id"], agent["id"])
        models.update_transaction(tx["id"], state="AWAITING_APPROVAL", decision="APPROVAL_REQUIRED",
                                   merchant="Notion", amount=120.0, authorized_amount=120.0)
        models.reserve_budget(agent["id"], tx["id"], 120.0)
        before_spent = models.get_spent_since(agent["id"], models.start_of_day_iso())
        assert before_spent == 120.0

        client.post(f"/agents/{agent['id']}/retire")

        cancelled_tx = client.get(f"/transactions/{tx['id']}").json()
        assert cancelled_tx["state"] == "CANCELLED"
        assert "removed" in cancelled_tx["decision_reason"].lower()
        # decision itself (APPROVAL_REQUIRED) is preserved as "how far this
        # got", not overwritten.
        assert cancelled_tx["decision"] == "APPROVAL_REQUIRED"

        cancelled_task = client.get(f"/tasks/{task['id']}").json()
        assert cancelled_task["status"] == "CANCELLED"

        after_spent = models.get_spent_since(agent["id"], models.start_of_day_iso())
        assert after_spent == 0.0  # budget reservation was released

        event_types = [e["event_type"] for e in cancelled_tx["timeline"]]
        assert "TASK_CANCELLED_AGENT_REMOVED" in event_types


def test_retiring_agent_cancels_scheduled_tasks():
    with TestClient(app) as client:
        agent = client.post("/agents", json=_agent_payload()).json()
        sched = client.post("/schedules", json={
            "agent_id": agent["id"], "prompt": "Renew monthly", "recurrence": "MONTHLY",
        }).json()
        assert sched["status"] == "ACTIVE"

        client.post(f"/agents/{agent['id']}/retire")

        refreshed = client.get(f"/schedules/{sched['id']}").json()
        assert refreshed["status"] == "CANCELLED"


def test_deleting_agent_removes_live_rows_but_keeps_audit_trail():
    with TestClient(app) as client:
        agent = client.post("/agents", json=_agent_payload()).json()
        agent_id = agent["id"]
        task = models.create_task(agent_id, "Renew the team's project tracker", None, None)
        tx = models.create_transaction(task["id"], agent_id)
        models.update_transaction(tx["id"], state="COMPLETED", decision="ALLOW", merchant="Notion")

        resp = client.delete(f"/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json() == {"deleted": True}

        # Live entity and everything that referenced it (cascade) is gone.
        assert client.get(f"/agents/{agent_id}").status_code == 404
        assert client.get(f"/tasks/{task['id']}").status_code == 404
        assert client.get(f"/transactions/{tx['id']}").status_code == 404
        assert models.get_agent(agent_id) is None

        # The permanent audit trail still has a record that this agent (and
        # its deletion) existed, even though the live row is gone.
        audit = list_audit(limit=500)
        agent_events = [a for a in audit if a.get("agent_id") == agent_id]
        assert any(a["event_type"] == "AGENT_DELETED" for a in agent_events)


def test_reactivating_agent_allows_new_tasks_again_without_reviving_cancelled_work():
    with TestClient(app) as client:
        agent = client.post("/agents", json=_agent_payload()).json()

        # Something in flight when the agent is retired...
        task = models.create_task(agent["id"], "Renew the team's project tracker", None, None)
        tx = models.create_transaction(task["id"], agent["id"])
        models.update_transaction(tx["id"], state="AWAITING_APPROVAL", decision="APPROVAL_REQUIRED",
                                   merchant="Notion", amount=120.0, authorized_amount=120.0)
        sched = client.post("/schedules", json={
            "agent_id": agent["id"], "prompt": "Renew monthly", "recurrence": "MONTHLY",
        }).json()

        client.post(f"/agents/{agent['id']}/retire")
        assert client.get(f"/agents/{agent['id']}").json()["status"] == "RETIRED"

        resp = client.post(f"/agents/{agent['id']}/reactivate")
        assert resp.status_code == 200
        reactivated = resp.json()
        assert reactivated["status"] == "ACTIVE"

        # ...stays cancelled; reactivating only re-enables *new* work.
        assert client.get(f"/transactions/{tx['id']}").json()["state"] == "CANCELLED"
        assert client.get(f"/schedules/{sched['id']}").json()["status"] == "CANCELLED"

        # New tasks are accepted again.
        accepted = client.post("/tasks", json={"agent_id": agent["id"], "prompt": "Renew Figma"})
        assert accepted.status_code != 400

        event_types = [e["event_type"] for e in client.get(f"/agents/{agent['id']}").json()["activity"]]
        assert "AGENT_REACTIVATED" in event_types


def test_reactivating_active_agent_is_a_no_op():
    with TestClient(app) as client:
        agent = client.post("/agents", json=_agent_payload()).json()
        resp = client.post(f"/agents/{agent['id']}/reactivate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACTIVE"


def test_reactivating_unknown_agent_returns_404():
    with TestClient(app) as client:
        resp = client.post("/agents/agent_does_not_exist/reactivate")
        assert resp.status_code == 404


def test_deleting_unknown_agent_returns_404():
    with TestClient(app) as client:
        resp = client.delete("/agents/agent_does_not_exist")
        assert resp.status_code == 404


def test_cancelled_transaction_cannot_be_resurrected_by_a_stale_transition():
    """The core safety guarantee: once a transaction has been force-cancelled
    (e.g. by retire_agent), a straggling in-flight code path that still
    thinks it is in the old state must not be able to blindly overwrite
    CANCELLED back onto an active state."""
    with TestClient(app) as client:
        agent = client.post("/agents", json=_agent_payload()).json()
        task = models.create_task(agent["id"], "Renew the team's project tracker", None, None)
        tx = models.create_transaction(task["id"], agent["id"])
        models.update_transaction(tx["id"], state="RESEARCHING")

        # retire_agent force-cancels it...
        import asyncio
        asyncio.run(orchestrator._cancel_task(tx["id"], task["id"], agent["id"], "Agent removed."))
        assert models.get_transaction(tx["id"])["state"] == "CANCELLED"

        # ...and a straggling caller that still believes it was RESEARCHING
        # must be refused, not allowed to overwrite it back to PROPOSED.
        try:
            _set_tx_state(tx["id"], "RESEARCHING", "PROPOSED")
            assert False, "expected InvalidTransition"
        except InvalidTransition:
            pass
        assert models.get_transaction(tx["id"])["state"] == "CANCELLED"
