"""A transaction in RESEARCHING/PROPOSED/POLICY_CHECK/AUTHORIZED/CREATED can
only ever move forward via the one background coroutine run_task/resume_task
kicked off for it (asyncio.create_task) - there is no human action and no
external system (unlike VERIFYING, which waits on PayPal) that will ever
nudge it along. If the process running that coroutine dies mid-flight (a
crash, a deploy, a sandbox reset), the transaction - and any budget policy
already reserved for it - is stuck forever with nothing watching for it.

Covers orchestrator.reconcile_orphaned_transaction(s): the general safety
net mirroring the existing stale-VERIFYING reconciler, but for every other
non-terminal state a dead background coroutine can leave stranded.
"""
from __future__ import annotations

import pytest

import app.agent.orchestrator as orchestrator
from app.database import models
from app.database.database import get_connection, immediate_transaction


def _agent_and_policy():
    agent = models.create_agent("Procurement Agent", "Buy software", "Buy cheap software")
    models.create_policy(agent["id"], {
        "max_transaction_amount": 200, "approval_threshold": 150,
        "daily_limit": 500, "monthly_limit": 3000,
        "velocity": {"max_transactions": 5, "window_minutes": 60},
        "blocked_categories": [], "allowed_categories": [],
    })
    return agent


def _task_and_tx(agent, state: str, *, authorized_amount: float | None = None):
    task = models.create_task(agent["id"], "Buy analytics software", 150)
    tx = models.create_transaction(task["id"], agent["id"])
    models.add_activity(agent["id"], task["id"], tx["id"], "TASK_CREATED", "New task submitted.", {})
    models.add_activity(agent["id"], task["id"], tx["id"], "AGENT_STARTED", "Agent started.", {})
    fields = {"state": state}
    if authorized_amount is not None:
        with immediate_transaction():
            models.reserve_budget(agent["id"], tx["id"], authorized_amount)
        fields["authorized_amount"] = authorized_amount
    models.update_transaction(tx["id"], **fields)
    return models.get_task(task["id"]), models.get_transaction(tx["id"])


def _net_reserved(agent_id: str) -> float:
    row = get_connection().execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM budget_ledger WHERE agent_id=?",
        (agent_id,),
    ).fetchone()
    return float(row["total"])


def _backdate_updated_at(tx_id: str, iso: str) -> None:
    get_connection().execute("UPDATE transactions SET updated_at=? WHERE id=?", (iso, tx_id))


def _backdate_all_activity(task_id: str, iso: str) -> None:
    get_connection().execute("UPDATE activity_events SET created_at=? WHERE task_id=?", (iso, task_id))


OLD = "2020-01-01T00:00:00.000000Z"


# --------------------------------------------------------------- models layer --
def test_list_stale_active_transactions_filters_by_state_and_age():
    agent = _agent_and_policy()
    _task, stale = _task_and_tx(agent, "RESEARCHING")
    _backdate_updated_at(stale["id"], OLD)
    _task2, fresh = _task_and_tx(agent, "RESEARCHING")
    _task3, wrong_state = _task_and_tx(agent, "VERIFYING")
    _backdate_updated_at(wrong_state["id"], OLD)

    cutoff = models.window_start_iso(10)
    found = {row["id"] for row in models.list_stale_active_transactions(["RESEARCHING"], cutoff)}

    assert stale["id"] in found
    assert fresh["id"] not in found
    assert wrong_state["id"] not in found, "VERIFYING is reconciled separately, not by this general sweep"


def test_get_last_activity_at_returns_most_recent_event():
    agent = _agent_and_policy()
    task, tx = _task_and_tx(agent, "RESEARCHING")
    models.add_activity(agent["id"], task["id"], tx["id"], "SEARCH_STARTED", "Searching...", {})

    last = models.get_last_activity_at(task["id"])
    assert last is not None
    # The just-added SEARCH_STARTED event is newer than (or equal to, on a
    # fast test run) the TASK_CREATED/AGENT_STARTED pair seeded in _task_and_tx.
    all_events = models.list_activity(task_id=task["id"], order="asc")
    assert last == all_events[-1]["created_at"]


# ------------------------------------------------------- orphan reconciliation --
@pytest.mark.asyncio
async def test_truly_silent_researching_task_gets_failed_and_budget_released():
    agent = _agent_and_policy()
    task, tx = _task_and_tx(agent, "AUTHORIZED", authorized_amount=63.99)
    _backdate_updated_at(tx["id"], OLD)
    _backdate_all_activity(task["id"], OLD)
    assert _net_reserved(agent["id"]) == pytest.approx(63.99)

    await orchestrator.reconcile_orphaned_transaction(tx)

    updated = models.get_transaction(tx["id"])
    assert updated["state"] == "FAILED"
    assert "resubmit" in updated["error"].lower()
    assert models.get_task(task["id"])["status"] == "FAILED"
    assert _net_reserved(agent["id"]) == pytest.approx(0.0), (
        "an orphaned transaction that had reserved budget must give it back"
    )


@pytest.mark.asyncio
async def test_still_actively_progressing_task_is_left_alone():
    """The transaction's own updated_at is old (RESEARCHING doesn't touch
    it on every step), but a *recent* activity event proves a background
    loop is still genuinely working, just slowly - must not be failed out
    from under it."""
    agent = _agent_and_policy()
    task, tx = _task_and_tx(agent, "RESEARCHING")
    _backdate_updated_at(tx["id"], OLD)
    _backdate_all_activity(task["id"], OLD)
    # ...but a fresh event just landed, proving it's still alive.
    models.add_activity(agent["id"], task["id"], tx["id"], "SEARCH_STARTED",
                         "Searching the web for \"software $200\"...", {})

    await orchestrator.reconcile_orphaned_transaction(tx)

    assert models.get_transaction(tx["id"])["state"] == "RESEARCHING", (
        "recent activity means this is slow, not abandoned - must not be touched"
    )


@pytest.mark.asyncio
async def test_needs_input_task_is_never_touched_even_if_very_old():
    """NEEDS_INPUT is a deliberate pause for a human reply with full
    conversation state persisted - not lost work. It must never be failed
    by this sweep no matter how long it's been waiting."""
    agent = _agent_and_policy()
    task, tx = _task_and_tx(agent, "NEEDS_INPUT")
    _backdate_updated_at(tx["id"], OLD)
    _backdate_all_activity(task["id"], OLD)

    count = await orchestrator.reconcile_orphaned_transactions()

    assert count == 0
    assert models.get_transaction(tx["id"])["state"] == "NEEDS_INPUT"


@pytest.mark.asyncio
async def test_awaiting_approval_task_is_never_touched_even_if_very_old():
    """Same reasoning as NEEDS_INPUT: a human owner approving in the UI is
    the only thing that should ever move this forward."""
    agent = _agent_and_policy()
    task, tx = _task_and_tx(agent, "AWAITING_APPROVAL")
    _backdate_updated_at(tx["id"], OLD)
    _backdate_all_activity(task["id"], OLD)

    count = await orchestrator.reconcile_orphaned_transactions()

    assert count == 0
    assert models.get_transaction(tx["id"])["state"] == "AWAITING_APPROVAL"


@pytest.mark.asyncio
async def test_verifying_task_is_not_handled_by_this_sweep_even_if_very_old():
    """VERIFYING has its own dedicated reconciler (it must check PayPal
    first) - this general sweep must leave it alone entirely."""
    agent = _agent_and_policy()
    task, tx = _task_and_tx(agent, "VERIFYING")
    _backdate_updated_at(tx["id"], OLD)
    _backdate_all_activity(task["id"], OLD)

    count = await orchestrator.reconcile_orphaned_transactions()

    assert count == 0
    assert models.get_transaction(tx["id"])["state"] == "VERIFYING"


@pytest.mark.asyncio
async def test_sweep_resolves_every_genuinely_orphaned_transaction_in_one_pass():
    agent = _agent_and_policy()
    _task1, orphan_researching = _task_and_tx(agent, "RESEARCHING")
    _backdate_updated_at(orphan_researching["id"], OLD)
    _backdate_all_activity(_task1["id"], OLD)

    _task2, orphan_proposed = _task_and_tx(agent, "PROPOSED")
    _backdate_updated_at(orphan_proposed["id"], OLD)
    _backdate_all_activity(_task2["id"], OLD)

    _task3, still_working = _task_and_tx(agent, "POLICY_CHECK")
    _backdate_updated_at(still_working["id"], OLD)
    # No backdated activity for this one - its TASK_CREATED/AGENT_STARTED
    # events are fresh (created moments ago by _task_and_tx itself).

    count = await orchestrator.reconcile_orphaned_transactions()

    assert count == 2
    assert models.get_transaction(orphan_researching["id"])["state"] == "FAILED"
    assert models.get_transaction(orphan_proposed["id"])["state"] == "FAILED"
    assert models.get_transaction(still_working["id"])["state"] == "POLICY_CHECK"


@pytest.mark.asyncio
async def test_reconcile_never_releases_budget_that_was_never_reserved():
    """Most orphaned transactions (CREATED, RESEARCHING, PROPOSED,
    POLICY_CHECK before an ALLOW/APPROVAL_REQUIRED decision) never had
    budget reserved at all - must stay a harmless no-op for those."""
    agent = _agent_and_policy()
    task, tx = _task_and_tx(agent, "RESEARCHING")
    _backdate_updated_at(tx["id"], OLD)
    _backdate_all_activity(task["id"], OLD)

    await orchestrator.reconcile_orphaned_transaction(tx)

    assert models.get_transaction(tx["id"])["state"] == "FAILED"
    assert _net_reserved(agent["id"]) == pytest.approx(0.0)
