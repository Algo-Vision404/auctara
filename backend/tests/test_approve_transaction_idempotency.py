"""approve_transaction (POST /transactions/{id}/approve) is the other place,
besides the PayPal return-redirect, where a plain read-check used to sit
directly in front of a real external side effect: moving AWAITING_APPROVAL
-> AUTHORIZED then immediately calling execute_payment, which creates a
real PayPal order. The frontend's Approve button already disables itself
while a click is in flight, but that's a single-tab, single-click guard -
it cannot stop two open tabs on the same transaction, a client retry after
a timeout, or a double-tap that lands two independent requests before the
first response comes back.

_set_tx_state used to do a plain SELECT-then-UPDATE with no transaction
wrapping it, so two concurrent approve_transaction calls could both read
AWAITING_APPROVAL before either wrote, both "win", and both go on to call
execute_payment - creating two separate real PayPal orders for one
purchase. The fix (models.atomic_transition) makes that read-check-and-
write a single conditional UPDATE inside BEGIN IMMEDIATE, so at most one
caller can ever move the row and therefore at most one can ever reach
execute_payment.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

import app.agent.orchestrator as orchestrator
from app.database import models


def _awaiting_approval_transaction():
    agent = models.create_agent("Procurement Agent", "Buy software", "Buy cheap software")
    models.create_policy(agent["id"], {
        "max_transaction_amount": 500, "approval_threshold": 50,
        "daily_limit": 2000, "monthly_limit": 10000,
        "velocity": {"max_transactions": 5, "window_minutes": 60},
        "blocked_categories": [], "allowed_categories": [],
    })
    task = models.create_task(agent["id"], "Buy analytics software", 300)
    tx = models.create_transaction(task["id"], agent["id"])
    models.update_transaction(
        tx["id"],
        state="AWAITING_APPROVAL",
        merchant="Acme Analytics",
        amount=199.0,
        expected_amount=199.0,
        currency="USD",
        category="software",
        reason="Renew analytics subscription",
        decision="APPROVAL_REQUIRED",
        authorized_amount=199.0,
    )
    return models.get_transaction(tx["id"])


@pytest.mark.asyncio
async def test_approve_on_an_already_authorized_transaction_raises(monkeypatch):
    """Sanity check of the existing (unchanged) hard-error case: approving a
    transaction that isn't actually AWAITING_APPROVAL must still fail
    loudly, not silently succeed."""
    tx = _awaiting_approval_transaction()
    models.update_transaction(tx["id"], state="AUTHORIZED")

    with pytest.raises(orchestrator.AgentError):
        await orchestrator.approve_transaction(tx["id"])


def test_concurrent_approvals_only_create_one_paypal_order(monkeypatch):
    """Real-thread concurrency test, same technique already proven against
    the audit chain, scheduler and PayPal-continue races: asyncio alone
    cannot exercise this, since nothing in the old buggy code awaited
    between its read and its write, so the race must come from genuinely
    parallel OS threads each with their own SQLite connection and event
    loop.
    """
    tx = _awaiting_approval_transaction()
    create_order_calls = []
    lock = threading.Lock()

    async def fake_create_order(**kwargs):
        with lock:
            create_order_calls.append(kwargs)
        # Widen the race window the same way the proof-of-bug patches did
        # for the scheduler/audit bugs, so a non-atomic implementation
        # reliably loses the race within the test run instead of just
        # usually getting lucky.
        await asyncio.sleep(0.01)
        return {"order_id": f"ORDER{len(create_order_calls)}", "status": "PAYER_ACTION_REQUIRED",
                "authorization_id": None, "approve_url": "https://sandbox.paypal.com/approve/X"}

    monkeypatch.setattr(orchestrator.paypal_orders, "create_order", fake_create_order)

    results: list[dict | None] = []
    errors: list[Exception] = []
    results_lock = threading.Lock()

    def worker():
        try:
            result = asyncio.run(orchestrator.approve_transaction(tx["id"]))
            with results_lock:
                results.append(result)
        except (orchestrator.InvalidTransition, orchestrator.AgentError):
            # Expected for every loser: either it lost the atomic claim
            # inside _set_tx_state (InvalidTransition), or by the time it
            # even got to its own leading read-check the winner had
            # already moved the transaction past AWAITING_APPROVAL
            # (AgentError "not awaiting approval") - both mean "did not
            # create a PayPal order", which is exactly what's asserted
            # below via create_order_calls.
            with results_lock:
                results.append(None)
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"approve_transaction raised under concurrency: {errors}"
    assert len(create_order_calls) == 1, (
        f"expected exactly one PayPal order to ever be created, got {len(create_order_calls)}"
    )
    # Exactly one thread actually moved the transaction and called execute_payment;
    # the rest must have lost the race before ever reaching create_order.
    succeeded = [r for r in results if r is not None]
    assert len(succeeded) == 1
