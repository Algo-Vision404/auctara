"""continue_after_paypal_approval is reachable as a genuinely independent
HTTP request every time PayPal (or the user) redirects back to
`/transactions/{id}?paypal=return`. The frontend already guards against
re-firing it from the same page instance (a ref flag that survives React
Strict Mode's double-effect dev behavior), but that cannot protect against
a page refresh while that query param is still in the URL, the user
hitting back/forward, or PayPal itself redirecting twice - each of which
hits this endpoint again as a brand new request. Without a server-side
claim, two such calls could both see state=VERIFYING and both call
PayPal's authorize/capture APIs for the same order: a real double-charge,
not just a duplicate UI event.

These tests cover both the practical behavior (duplicate calls must not
call PayPal twice, and must not surface a scary error for what is actually
a harmless duplicate) and the underlying atomic primitive itself, under
real concurrency.
"""
from __future__ import annotations

import threading

import pytest

import app.agent.orchestrator as orchestrator
from app.database import models


def _verifying_transaction():
    """A transaction sitting exactly where PayPal's redirect flow leaves it:
    VERIFYING, with a real order id, waiting for continue_after_paypal_approval
    to authorize + capture it - the standard-checkout path, as opposed to
    the immediate-authorization path that never needs this endpoint at all.
    """
    agent = models.create_agent("Procurement Agent", "Buy software", "Buy cheap software")
    models.create_policy(agent["id"], {
        "max_transaction_amount": 200, "approval_threshold": 150,
        "daily_limit": 500, "monthly_limit": 3000,
        "velocity": {"max_transactions": 5, "window_minutes": 60},
        "blocked_categories": [], "allowed_categories": [],
    })
    task = models.create_task(agent["id"], "Buy analytics software", 150)
    tx = models.create_transaction(task["id"], agent["id"])
    models.update_transaction(
        tx["id"],
        state="VERIFYING",
        paypal_order_id="ORDER123",
        expected_amount=63.99,
        authorized_amount=63.99,
    )
    return models.get_transaction(tx["id"])


@pytest.mark.asyncio
async def test_duplicate_continue_calls_only_touch_paypal_once(monkeypatch):
    tx = _verifying_transaction()
    authorize_calls = []
    capture_calls = []

    async def fake_authorize_order(order_id):
        authorize_calls.append(order_id)
        return {"order_id": order_id, "authorization_id": "AUTH123",
                "authorized_amount": 63.99, "status": "CREATED"}

    async def fake_capture_authorization(authorization_id, mock_response=None):
        capture_calls.append(authorization_id)
        return {"capture_id": "CAPTURE789", "status": "COMPLETED", "amount": 63.99}

    monkeypatch.setattr(orchestrator.paypal_orders, "authorize_order", fake_authorize_order)
    monkeypatch.setattr(orchestrator.paypal_orders, "capture_authorization", fake_capture_authorization)

    first = await orchestrator.continue_after_paypal_approval(tx["id"])
    assert first["state"] == "COMPLETED"
    assert len(authorize_calls) == 1
    assert len(capture_calls) == 1

    # A second, independent call to the exact same endpoint (page refresh,
    # back/forward, duplicate redirect) must not touch PayPal again, and
    # must not error - it should just report the real (already-completed)
    # state.
    second = await orchestrator.continue_after_paypal_approval(tx["id"])
    assert second["state"] == "COMPLETED"
    assert len(authorize_calls) == 1, "a duplicate call re-authorized the same PayPal order"
    assert len(capture_calls) == 1, "a duplicate call re-captured the same PayPal order"


@pytest.mark.asyncio
async def test_continue_on_unknown_or_never_submitted_transaction_still_errors(monkeypatch):
    """The softened 'already handled, return current state' behavior must
    only apply to a transaction that genuinely went through PayPal - not
    paper over a request for a transaction that was never submitted to
    PayPal at all, or doesn't exist."""
    agent = models.create_agent("Procurement Agent", "Buy software", "Buy cheap software")
    task = models.create_task(agent["id"], "Buy analytics software", 150)
    tx = models.create_transaction(task["id"], agent["id"])  # state=CREATED, no paypal_order_id

    with pytest.raises(orchestrator.AgentError):
        await orchestrator.continue_after_paypal_approval(tx["id"])

    with pytest.raises(orchestrator.AgentError):
        await orchestrator.continue_after_paypal_approval("tx_doesnotexist")


def test_concurrent_claims_on_the_same_transaction_never_both_win():
    """claim_paypal_continue is the primitive that makes the above safe.
    asyncio can't actually exercise the race (every step from read to
    write in continue_after_paypal_approval is synchronous or already
    resolved by the time it matters), so this hits the primitive directly
    from real OS threads, each with their own SQLite connection - the same
    technique already proven against the audit chain and scheduler claims.
    """
    tx = _verifying_transaction()

    results: list[bool] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker():
        try:
            won = models.claim_paypal_continue(tx["id"])
            with lock:
                results.append(won)
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"claim_paypal_continue raised under concurrency: {errors}"
    assert results.count(True) == 1, f"expected exactly one winner, got {results}"
    assert results.count(False) == 7
