"""PayPal Orders v2 flow, using intent=AUTHORIZE for true two-phase safety:

  create_order()   -> places a hold (authorization) for the proposed amount
  get_order()      -> retrieve current state (used to verify before capture)
  capture_authorization() -> release the hold and take the money
  void_authorization()    -> release the hold without charging

Every call goes through PayPal's own official `paypal-server-sdk`
(`client.orders`, `client.payments` — APIMatic-generated controllers), not
hand-rolled REST requests: request bodies are built from the SDK's typed
models (`OrderRequest`, `PurchaseUnitRequest`, `Money`, ...) so a malformed
field is a Python-level error before anything is sent, and PayPal's SDK
owns auth, retries, and typed error exceptions. The functions below keep
their original names and return shapes exactly, so nothing upstream
(orchestrator, routes) had to change for this migration.

If a sandbox test card is configured (PAYPAL_TEST_CARD_*), the order is
created with a direct card payment_source so the authorization completes
synchronously (no buyer browser redirect needed) — this is the path used
for an agent acting autonomously on a payment method already on file.
Otherwise a standard "approve" link is returned, and the frontend sends the
shopper to PayPal Sandbox to approve the order like a normal checkout.
"""
from __future__ import annotations

import uuid
from typing import Optional

from paypalserversdk.models.card_request import CardRequest
from paypalserversdk.models.checkout_payment_intent import CheckoutPaymentIntent
from paypalserversdk.models.money import Money
from paypalserversdk.models.order_application_context import OrderApplicationContext
from paypalserversdk.models.order_request import OrderRequest
from paypalserversdk.models.payment_source import PaymentSource
from paypalserversdk.models.purchase_unit_request import PurchaseUnitRequest

from app.config import get_settings
from app.paypal.client import (
    PAYPAL_SDK_EXCEPTIONS,
    get_paypal_client,
    to_wire_dict,
    translate_sdk_error,
)

RETURN_REPRESENTATION = "return=representation"


def _card_payment_source() -> Optional[PaymentSource]:
    s = get_settings()
    if not (s.paypal_test_card_number and s.paypal_test_card_expiry and s.paypal_test_card_cvv):
        return None
    return PaymentSource(
        card=CardRequest(
            number=s.paypal_test_card_number,
            expiry=s.paypal_test_card_expiry,
            security_code=s.paypal_test_card_cvv,
            name=s.paypal_test_card_name or "AgentAuth Agent",
        )
    )


async def create_order(amount: float, currency: str, description: str,
                        return_url: str, cancel_url: str, custom_id: str) -> dict:
    client = get_paypal_client()

    purchase_unit = PurchaseUnitRequest(
        amount=Money(currency_code=currency.upper(), value=f"{amount:.2f}"),
        custom_id=custom_id,
        description=description[:127] if description else "AgentAuth purchase",
    )
    application_context = OrderApplicationContext(
        return_url=return_url,
        cancel_url=cancel_url,
        brand_name="AgentAuth",
        shipping_preference="NO_SHIPPING",
        user_action="PAY_NOW",
    )
    order_kwargs = dict(
        intent=CheckoutPaymentIntent.AUTHORIZE,
        purchase_units=[purchase_unit],
        application_context=application_context,
    )
    card_source = _card_payment_source()
    if card_source:
        order_kwargs["payment_source"] = card_source
    order_request = OrderRequest(**order_kwargs)

    # PayPal requires a PayPal-Request-Id (idempotency key) on any single-step
    # create-order-with-payment-source call — i.e. whenever we hand over a
    # card directly instead of waiting for buyer approval. Without it PayPal
    # rejects the request with PAYPAL_REQUEST_ID_REQUIRED.
    request_options = {"body": order_request, "prefer": RETURN_REPRESENTATION}
    if card_source:
        request_options["paypal_request_id"] = f"agentauth-{custom_id}-{uuid.uuid4().hex[:12]}"

    try:
        result = client.orders.create_order(request_options)
    except PAYPAL_SDK_EXCEPTIONS as exc:
        raise translate_sdk_error(exc, "PayPal order creation failed") from exc

    return _summarize_order(to_wire_dict(result.body))


async def get_order(order_id: str) -> dict:
    client = get_paypal_client()
    try:
        result = client.orders.get_order({"id": order_id})
    except PAYPAL_SDK_EXCEPTIONS as exc:
        raise translate_sdk_error(exc, "PayPal order lookup failed") from exc
    return _summarize_order(to_wire_dict(result.body))


async def authorize_order(order_id: str) -> dict:
    """Used after a buyer has approved the order via the redirect flow."""
    client = get_paypal_client()
    try:
        result = client.orders.authorize_order({
            "id": order_id,
            "prefer": RETURN_REPRESENTATION,
        })
    except PAYPAL_SDK_EXCEPTIONS as exc:
        raise translate_sdk_error(exc, "PayPal authorization failed") from exc
    return _summarize_order(to_wire_dict(result.body))


async def capture_authorization(authorization_id: str) -> dict:
    client = get_paypal_client()
    try:
        result = client.payments.capture_authorized_payment({
            "authorization_id": authorization_id,
            "prefer": RETURN_REPRESENTATION,
        })
    except PAYPAL_SDK_EXCEPTIONS as exc:
        raise translate_sdk_error(exc, "PayPal capture failed") from exc

    captured = to_wire_dict(result.body) or {}
    return {
        "capture_id": captured.get("id"),
        "status": captured.get("status"),
        "amount": _amount_value(captured.get("amount")),
        "currency": (captured.get("amount") or {}).get("currency_code"),
        "raw_status_code": result.status_code,
    }


async def void_authorization(authorization_id: str) -> dict:
    client = get_paypal_client()
    try:
        result = client.payments.void_payment({
            "authorization_id": authorization_id,
            "prefer": RETURN_REPRESENTATION,
        })
    except PAYPAL_SDK_EXCEPTIONS as exc:
        raise translate_sdk_error(exc, "PayPal void failed") from exc
    return {"voided": True, "raw": to_wire_dict(result.body) or {"status_code": result.status_code}}


def _amount_value(amount: dict | None) -> float | None:
    if not amount:
        return None
    try:
        return float(amount.get("value"))
    except (TypeError, ValueError):
        return None


def _summarize_order(order: dict) -> dict:
    links = {l.get("rel"): l.get("href") for l in order.get("links", [])}
    purchase_unit = (order.get("purchase_units") or [{}])[0]
    payments = purchase_unit.get("payments") or {}
    authorizations = payments.get("authorizations") or []
    authorization = authorizations[0] if authorizations else None

    return {
        "order_id": order.get("id"),
        "status": order.get("status"),
        "approve_url": links.get("approve"),
        "self_url": links.get("self"),
        "authorization_id": authorization.get("id") if authorization else None,
        "authorized_amount": _amount_value(authorization.get("amount")) if authorization else None,
        "authorization_status": authorization.get("status") if authorization else None,
        "requested_amount": _amount_value(purchase_unit.get("amount")),
        "currency": (purchase_unit.get("amount") or {}).get("currency_code"),
        "raw": order,
    }
