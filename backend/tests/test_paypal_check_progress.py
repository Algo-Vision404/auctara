"""check_paypal_order_progress is the endpoint a frontend can poll freely,
on a timer and on tab-focus, while a transaction sits in VERIFYING waiting
on the buyer to approve at PayPal - instead of (or in addition to) relying
on PayPal's own return redirect, which this app's sandboxed preview host
can silently block for a real external top-level navigation. Unlike
continue_after_paypal_approval (which assumes approval already happened,
since it only ever runs off a genuine PayPal redirect return) this must
NEVER fail a transaction just because the buyer has not finished yet - it
should only ever report "still waiting" until PayPal itself says
otherwise, and only then advance the transaction forward exactly once.
"""
from __future__ import annotations

import pytest

import app.agent.orchestrator as orchestrator
from app.database import models
from app.paypal.client import PayPalError


def _verifying_transaction():
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
async def test_check_while_buyer_has_not_approved_yet_leaves_transaction_untouched(monkeypatch):
    tx = _verifying_transaction()
    authorize_calls = []

    async def fake_get_order(order_id):
        return {"order_id": order_id, "status": "CREATED", "authorization_id": None}

    async def fake_authorize_order(order_id):
        authorize_calls.append(order_id)
        raise AssertionError("must not authorize an order the buyer has not approved yet")

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)
    monkeypatch.setattr(orchestrator.paypal_orders, "authorize_order", fake_authorize_order)

    for _ in range(5):  # repeated polling must stay harmless every time
        result = await orchestrator.check_paypal_order_progress(tx["id"])
        assert result["state"] == "VERIFYING"
        assert result["error"] is None

    assert authorize_calls == []


@pytest.mark.asyncio
async def test_check_after_buyer_approves_finishes_the_purchase(monkeypatch):
    tx = _verifying_transaction()
    authorize_calls = []
    capture_calls = []

    async def fake_get_order(order_id):
        return {"order_id": order_id, "status": "APPROVED", "authorization_id": None}

    async def fake_authorize_order(order_id):
        authorize_calls.append(order_id)
        return {"order_id": order_id, "authorization_id": "AUTH123",
                "authorized_amount": 63.99, "status": "CREATED"}

    async def fake_capture_authorization(authorization_id, mock_response=None):
        capture_calls.append(authorization_id)
        return {"capture_id": "CAPTURE789", "status": "COMPLETED", "amount": 63.99}

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)
    monkeypatch.setattr(orchestrator.paypal_orders, "authorize_order", fake_authorize_order)
    monkeypatch.setattr(orchestrator.paypal_orders, "capture_authorization", fake_capture_authorization)

    result = await orchestrator.check_paypal_order_progress(tx["id"])
    assert result["state"] == "COMPLETED"
    assert len(authorize_calls) == 1
    assert len(capture_calls) == 1

    # Calling it again afterward (e.g. one more poll tick landing just after
    # completion) must not touch PayPal again or change anything.
    again = await orchestrator.check_paypal_order_progress(tx["id"])
    assert again["state"] == "COMPLETED"
    assert len(authorize_calls) == 1
    assert len(capture_calls) == 1


@pytest.mark.asyncio
async def test_check_when_already_authorized_finalizes_without_reauthorizing(monkeypatch):
    """Covers the same lost-callback scenario as the stale-VERIFYING
    reconciler: PayPal shows the order already authorized (not just
    approved) because some earlier call succeeded on PayPal's side but its
    response never made it back here - must finish from the authorization
    already in hand, never call authorize_order a second time for it."""
    tx = _verifying_transaction()
    authorize_calls = []

    async def fake_get_order(order_id):
        return {"order_id": order_id, "status": "CREATED", "authorization_id": "AUTH999",
                "authorized_amount": 63.99}

    async def fake_authorize_order(order_id):
        authorize_calls.append(order_id)
        raise AssertionError("must not re-authorize an order that already has an authorization")

    async def fake_capture_authorization(authorization_id, mock_response=None):
        return {"capture_id": "CAPTURE999", "status": "COMPLETED", "amount": 63.99}

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)
    monkeypatch.setattr(orchestrator.paypal_orders, "authorize_order", fake_authorize_order)
    monkeypatch.setattr(orchestrator.paypal_orders, "capture_authorization", fake_capture_authorization)

    result = await orchestrator.check_paypal_order_progress(tx["id"])
    assert result["state"] == "COMPLETED"
    assert authorize_calls == []


@pytest.mark.asyncio
async def test_check_tolerates_a_transient_paypal_lookup_failure(monkeypatch):
    """A momentary network/API hiccup while just checking status must not
    fail the transaction outright - that would throw away a transaction
    over a problem that has nothing to do with whether the buyer actually
    approved it. The next poll tick gets another chance."""
    tx = _verifying_transaction()

    async def fake_get_order(order_id):
        raise PayPalError("temporary network blip")

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)

    result = await orchestrator.check_paypal_order_progress(tx["id"])
    assert result["state"] == "VERIFYING"
    assert result["error"] is None


@pytest.mark.asyncio
async def test_check_on_unknown_or_never_submitted_transaction_still_errors():
    agent = models.create_agent("Procurement Agent", "Buy software", "Buy cheap software")
    task = models.create_task(agent["id"], "Buy analytics software", 150)
    tx = models.create_transaction(task["id"], agent["id"])  # state=CREATED, no paypal_order_id

    with pytest.raises(orchestrator.AgentError):
        await orchestrator.check_paypal_order_progress(tx["id"])

    with pytest.raises(orchestrator.AgentError):
        await orchestrator.check_paypal_order_progress("tx_doesnotexist")


@pytest.mark.asyncio
async def test_check_after_transaction_already_resolved_is_a_pure_readonly_noop(monkeypatch):
    """Once a transaction has already left VERIFYING (finished by a real
    redirect, another poll, or the scheduler sweep), a trailing poll that
    arrives afterward must just report that - never touch PayPal at all."""
    tx = _verifying_transaction()
    models.update_transaction(tx["id"], state="COMPLETED")

    async def fake_get_order(order_id):
        raise AssertionError("must not call PayPal at all once already resolved")

    monkeypatch.setattr(orchestrator.paypal_orders, "get_order", fake_get_order)

    result = await orchestrator.check_paypal_order_progress(tx["id"])
    assert result["state"] == "COMPLETED"
