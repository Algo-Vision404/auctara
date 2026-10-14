"""A transaction moves to VERIFYING the instant a PayPal order is created,
and the only documented way out is the buyer approving on PayPal and the
frontend calling continue_after_paypal_approval on the redirect back. If
the buyer closes the tab, loses their connection, or that redirect simply
never arrives for any reason, nothing was ever watching for that - the
transaction (and the budget it reserved) was stuck in VERIFYING forever.

Also covers a related, more acute bug found alongside it: `_fail()`, the
one shared helper every PayPal-stage failure (order creation, authorization,
capture) already routed through, never released the budget it had
reserved - every such failure permanently locked that amount out of the
agent's budget even though no money was ever actually spent.
"""
from __future__ import annotations

import pytest

import app.agent.orchestrator as orchestrator
from app.database import models
from app.database.database import get_connection, immediate_transaction
from app.paypal.client import PayPalError


def _agent_and_policy():
    agent = models.create_agent("Procurement Agent", "Buy software", "Buy cheap software")
    models.create_policy(agent["id"], {
        "max_transaction_amount": 200, "approval_threshold": 150,
        "daily_limit": 500, "monthly_limit": 3000,
        "velocity": {"max_transactions": 5, "window_minutes": 60},
        "blocked_categories": [], "allowed_categories": [],
    })
    return agent


def _authorized_transaction(agent, *, amount: float = 63.99):
    """A transaction that policy actually ALLOWed - budget genuinely
    reserved, exactly like _evaluate_policy_atomic does for a real one -
    sitting in VERIFYING with a real PayPal order id, the normal spot
    every PayPal-stage failure or stall happens from."""
    task = models.create_task(agent["id"], "Buy analytics software", 150)
    tx = models.create_transaction(task["id"], agent["id"])
    with immediate_transaction():
        models.reserve_budget(agent["id"], tx["id"], amount)
    models.update_transaction(
        tx["id"],
        state="VERIFYING",
        paypal_order_id="ORDER123",
        expected_amount=amount,
        authorized_amount=amount,
    )
    return models.get_transaction(tx["id"])


def _net_reserved(agent_id: str) -> float:
    row = get_connection().execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM budget_ledger WHERE agent_id=?",
        (agent_id,),
    ).fetchone()
    return float(row["total"])


def _backdate_updated_at(tx_id: str, iso: str) -> None:
    get_connection().execute("UPDATE transactions SET updated_at=? WHERE id=?", (iso, tx_id))


# ------------------------------------------------------- _fail releases budget --
@pytest.mark.asyncio
async def test_fail_releases_a_reserved_budget_hold():
    agent = _agent_and_policy()
    tx = _authorized_transaction(agent)
    assert _net_reserved(agent["id"]) == pytest.approx(63.99)

    await orchestrator._fail(tx["id"], tx["task_id"], agent["id"], "PayPal order creation failed: boom")

    updated = models.get_transaction(tx["id"])
    assert updated["state"] == "FAILED"
    assert _net_reserved(agent["id"]) == pytest.approx(0.0), (
        "a transaction that failed after policy reserved budget for it must give that budget back"
    )


@pytest.mark.asyncio
async def test_fail_never_releases_budget_that_was_never_reserved():
    """Most _fail call sites (no active policy, research loop errors, a
    non-positive proposed price) happen before policy ever reserves
    anything - must stay a harmless no-op for those, not fabricate a
    release against nothing."""
    agent = _agent_and_policy()
    task = models.create_task(agent["id"], "Buy analytics software", 150)
    tx = models.create_transaction(task["id"], agent["id"])

    await orchestrator._fail(tx["id"], task["id"], agent["id"], "No active policy configured for this agent.")

    assert _net_reserved(agent["id"]) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_fail_called_twice_does_not_double_release():
    """_fail is explicitly safe to call on an already-terminal transaction
    (a no-op report, not a crash) - that must not also double-release (and
    over-credit) the budget ledger."""
    agent = _agent_and_policy()
    tx = _authorized_transaction(agent)

    await orchestrator._fail(tx["id"], tx["task_id"], agent["id"], "first failure")
    await orchestrator._fail(tx["id"], tx["task_id"], agent["id"], "second, duplicate call")

    assert _net_reserved(agent["id"]) == pytest.approx(0.0)


# ---------------------------------------------- stale VERIFYING reconciliation --
def test_list_stale_verifying_transactions_only_returns_old_enough_rows():
    agent = _agent_and_policy()
    fresh = _authorized_transaction(agent)
    stale = _authorized_transaction(agent)
    _backdate_updated_at(stale["id"], "2020-01-01T00:00:00.000000Z")

    cutoff = models.window_start_iso(30)
    found = {row["id"] for row in models.list_stale_verifying_transactions(cutoff)}

    assert stale["id"] in found
    assert fresh["id"] not in found


@pytest.mark.asyncio
async def test_reconcile_finalizes_a_transaction_paypal_says_was_actually_authorized(monkeypatch):
    """The buyer DID approve and the order WAS authorized on PayPal's side
    - only our own redirect callback never arrived. Must complete the
    payment exactly as the normal flow would, not wrongly fail (and
    refund the budget hold on) a purchase that actually went through."""
    agent = _agent_and_policy()
    tx = _authorized_transaction(agent)

    async def fake_get_order(order_id):
        return {"order_id": order_id, "status": "COMPLETED", "authorization_id": "AUTH1",
                "authorized_amount": 63.99, "requested_amount": 63.99}

    capture_calls = []

    async def fake_capture_authorization(authorization_id, mock_response=None):
        capture_calls.append(authorization_id)
        return {"capture_id": "CAP1", "status": "COMPLETED", "amount": 63.99}

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)
    monkeypatch.setattr(orchestrator.paypal_orders, "capture_authorization", fake_capture_authorization)

    await orchestrator.reconcile_stale_verifying_transaction(tx)

    updated = models.get_transaction(tx["id"])
    assert updated["state"] == "COMPLETED"
    assert len(capture_calls) == 1
    assert _net_reserved(agent["id"]) == pytest.approx(63.99), (
        "a completed purchase should keep its budget committed, not release it back"
    )


@pytest.mark.asyncio
async def test_reconcile_authorizes_and_finalizes_an_approved_but_unauthorized_order(monkeypatch):
    """The buyer approved, but PayPal never got (or we never received) the
    follow-up authorize call either. Must make it ourselves, same as the
    redirect-driven path does."""
    agent = _agent_and_policy()
    tx = _authorized_transaction(agent)

    async def fake_get_order(order_id):
        return {"order_id": order_id, "status": "APPROVED", "authorization_id": None}

    authorize_calls = []

    async def fake_authorize_order(order_id):
        authorize_calls.append(order_id)
        return {"order_id": order_id, "authorization_id": "AUTH1", "authorized_amount": 63.99,
                "status": "CREATED"}

    async def fake_capture_authorization(authorization_id, mock_response=None):
        return {"capture_id": "CAP1", "status": "COMPLETED", "amount": 63.99}

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)
    monkeypatch.setattr(orchestrator.paypal_orders, "authorize_order", fake_authorize_order)
    monkeypatch.setattr(orchestrator.paypal_orders, "capture_authorization", fake_capture_authorization)

    await orchestrator.reconcile_stale_verifying_transaction(tx)

    assert len(authorize_calls) == 1
    assert models.get_transaction(tx["id"])["state"] == "COMPLETED"


@pytest.mark.asyncio
async def test_reconcile_fails_and_releases_budget_when_buyer_never_approved(monkeypatch):
    """The buyer genuinely never came back and PayPal's own order shows no
    approval at all. This will never resolve itself - must fail it plainly
    and give the reserved budget back, instead of leaving it stuck."""
    agent = _agent_and_policy()
    tx = _authorized_transaction(agent)

    async def fake_get_order(order_id):
        return {"order_id": order_id, "status": "CREATED", "authorization_id": None}

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)

    await orchestrator.reconcile_stale_verifying_transaction(tx)

    updated = models.get_transaction(tx["id"])
    assert updated["state"] == "FAILED"
    assert "timed out" in updated["error"].lower()
    assert _net_reserved(agent["id"]) == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_reconcile_never_touches_paypal_for_a_transaction_a_real_return_already_claimed(monkeypatch):
    """A genuine buyer-return call (continue_after_paypal_approval) and
    this sweep share the same claim - if the real one got there first,
    the sweep must back off completely rather than racing it."""
    agent = _agent_and_policy()
    tx = _authorized_transaction(agent)
    assert models.claim_paypal_continue(tx["id"]) is True  # simulates a real in-flight return

    async def fake_get_order(order_id):
        raise AssertionError("must not call PayPal for a transaction another caller already claimed")

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)

    await orchestrator.reconcile_stale_verifying_transaction(tx)

    # Untouched - still VERIFYING, still holding its budget - exactly as it
    # should be while the real claim owner is (for all this sweep knows)
    # still mid-flight.
    assert models.get_transaction(tx["id"])["state"] == "VERIFYING"
    assert _net_reserved(agent["id"]) == pytest.approx(63.99)


@pytest.mark.asyncio
async def test_reconcile_sweep_handles_every_stale_transaction_in_one_pass(monkeypatch):
    agent = _agent_and_policy()
    stale_one = _authorized_transaction(agent)
    stale_two = _authorized_transaction(agent)
    fresh = _authorized_transaction(agent)
    _backdate_updated_at(stale_one["id"], "2020-01-01T00:00:00.000000Z")
    _backdate_updated_at(stale_two["id"], "2020-01-01T00:00:00.000000Z")

    async def fake_get_order(order_id):
        return {"order_id": order_id, "status": "CREATED", "authorization_id": None}

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)

    count = await orchestrator.reconcile_stale_verifying_transactions()

    assert count == 2
    assert models.get_transaction(stale_one["id"])["state"] == "FAILED"
    assert models.get_transaction(stale_two["id"])["state"] == "FAILED"
    assert models.get_transaction(fresh["id"])["state"] == "VERIFYING"


@pytest.mark.asyncio
async def test_reconcile_fails_plainly_if_paypal_itself_cannot_be_reached(monkeypatch):
    agent = _agent_and_policy()
    tx = _authorized_transaction(agent)

    async def fake_get_order(order_id):
        raise PayPalError("PayPal order lookup failed: upstream timeout")

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)

    await orchestrator.reconcile_stale_verifying_transaction(tx)

    updated = models.get_transaction(tx["id"])
    assert updated["state"] == "FAILED"
    assert _net_reserved(agent["id"]) == pytest.approx(0.0)
