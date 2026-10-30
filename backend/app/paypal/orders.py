"""PayPal Orders v2 flow, using intent=AUTHORIZE for true two-phase safety:

  create_order()   -> places a hold (authorization) for the proposed amount
  get_order()      -> retrieve current state (used to verify before capture)
  capture_authorization() -> release the hold and take the money
  void_authorization()    -> release the hold without charging

Every call goes through PayPal's own official `paypal-server-sdk`
(`client.orders`, `client.payments`, APIMatic-generated controllers), not
hand-rolled REST requests: request bodies are built from the SDK's typed
models (`OrderRequest`, `PurchaseUnitRequest`, `Money`, ...) so a malformed
field is a Python-level error before anything is sent, and PayPal's SDK
owns auth, retries, and typed error exceptions. The functions below keep
their original names and return shapes exactly, so nothing upstream
(orchestrator, routes) had to change for this migration.

If a sandbox test card is configured (PAYPAL_TEST_CARD_*), the order is
created with a direct card payment_source so the authorization completes
synchronously (no buyer browser redirect needed). This is the path used
for an agent acting autonomously on a payment method already on file.
Otherwise a standard "approve" link is returned, and the frontend sends the
shopper to PayPal Sandbox to approve the order like a normal checkout.
"""
from __future__ import annotations

import json
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

# PayPal's own documented, officially-supported sandbox negative-testing
# codes for the "Capture payment for order" family of endpoints (see
# docs/NEGATIVE_TESTING.md). Kept as an explicit allow-list, rather than
# accepting any caller-supplied string, so this opt-in QA hook can only ever
# request a real scenario PayPal itself documents - never an arbitrary value.
NEGATIVE_TEST_CODES = {
    "INSTRUMENT_DECLINED": "Card declined at capture (buyer's payment instrument is rejected)",
    "TRANSACTION_REFUSED": "Transaction refused by PayPal's payment engine",
    "INTERNAL_SERVER_ERROR": "PayPal service error (HTTP 500) during capture",
}


def _card_payment_source() -> Optional[PaymentSource]:
    s = get_settings()
    if not (s.paypal_test_card_number and s.paypal_test_card_expiry and s.paypal_test_card_cvv):
        return None
    return PaymentSource(
        card=CardRequest(
            number=s.paypal_test_card_number,
            expiry=s.paypal_test_card_expiry,
            security_code=s.paypal_test_card_cvv,
            name=s.paypal_test_card_name or "Auctara Agent",
        )
    )


async def create_order(amount: float, currency: str, description: str,
                        return_url: str, cancel_url: str, custom_id: str) -> dict:
    client = get_paypal_client()

    purchase_unit = PurchaseUnitRequest(
        amount=Money(currency_code=currency.upper(), value=f"{amount:.2f}"),
        custom_id=custom_id,
        description=description[:127] if description else "Auctara purchase",
    )
    application_context = OrderApplicationContext(
        return_url=return_url,
        cancel_url=cancel_url,
        brand_name="Auctara",
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
    # create-order-with-payment-source call, i.e. whenever we hand over a
    # card directly instead of waiting for buyer approval. Without it PayPal
    # rejects the request with PAYPAL_REQUEST_ID_REQUIRED.
    #
    # Deterministic, derived only from this transaction's own id - not a
    # fresh uuid appended on every call. An idempotency key's entire job is
    # letting PayPal recognize "I've already done this exact request" and
    # hand back the original result instead of doing it again; a key that's
    # different every time this function runs can never do that, no matter
    # what calls it. That matters here specifically because the PayPal SDK
    # this app uses "owns auth, retries, and typed error exceptions" (see
    # module docstring) - i.e. it may itself retry on a network blip/timeout
    # without this code ever knowing a retry happened. If the order actually
    # reached PayPal on an earlier attempt whose response we never saw, a
    # random key on the retry would create a second real authorization for
    # the same purchase, with no way for our own database to ever learn
    # that second hold exists. create_order is only ever invoked once per
    # transaction in this codebase (see orchestrator.execute_payment), so
    # the transaction id alone is a safe, sufficient, stable key.
    request_options = {"body": order_request, "prefer": RETURN_REPRESENTATION}
    if card_source:
        request_options["paypal_request_id"] = f"auctara-order-{custom_id}"

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
    """Used after a buyer has approved the order via the redirect flow.

    Sends a deterministic PayPal-Request-Id derived only from the order's
    own id. PayPal documents PayPal-Request-Id as "recommended for all POST
    and PUT calls" precisely so a network timeout/5xx can be safely retried
    with the same key and get back the original result instead of PayPal
    doing the action again - without it, a retried authorize call after a
    lost response risks a second real authorization for the same order.
    Keying on order_id (not a random value) means every retry of "authorize
    this order" - whoever makes it, whenever - sends the same key.
    """
    client = get_paypal_client()
    try:
        result = client.orders.authorize_order({
            "id": order_id,
            "prefer": RETURN_REPRESENTATION,
            "paypal_request_id": f"auctara-authorize-{order_id}",
        })
    except PAYPAL_SDK_EXCEPTIONS as exc:
        raise translate_sdk_error(exc, "PayPal authorization failed") from exc
    return _summarize_order(to_wire_dict(result.body))


async def capture_authorization(authorization_id: str, mock_response: str | None = None) -> dict:
    """`mock_response`, when set, is one of PayPal's own documented sandbox
    negative-testing codes for this endpoint (e.g. "INSTRUMENT_DECLINED",
    "TRANSACTION_REFUSED", "INTERNAL_SERVER_ERROR" - see
    https://developer.paypal.com/tools/sandbox/negative-testing/request-headers/
    and docs/NEGATIVE_TESTING.md). It makes PayPal's own real sandbox API
    genuinely return that real, documented error for this one call, via the
    PayPal-Mock-Response header the SDK exposes as `paypal_mock_response` -
    this is PayPal's own supported QA mechanism, not anything fabricated by
    this codebase. None (the default, used by every normal transaction)
    requests nothing special and captures for real, exactly as before.

    Also sends a deterministic PayPal-Request-Id keyed on authorization_id.
    PayPal's own docs call this out explicitly for /capture specifically:
    "An HTTP 5xx or network timeout from an /execute or /capture endpoint
    could have resulted in the creation of a PayPal transaction. To be
    informed of the transaction, it is recommended that you repeat the same
    /execute or /capture call at least once, with the same PayPal-Request-Id
    HTTP header as before." Without this header a lost response after a real
    capture went through could, on retry, actually charge the buyer twice
    for the same authorization instead of returning the original capture.
    """
    client = get_paypal_client()
    options = {
        "authorization_id": authorization_id,
        "prefer": RETURN_REPRESENTATION,
        "paypal_request_id": f"auctara-capture-{authorization_id}",
    }
    if mock_response:
        options["paypal_mock_response"] = json.dumps({"mock_application_codes": mock_response})
    try:
        result = client.payments.capture_authorized_payment(options)
    except PAYPAL_SDK_EXCEPTIONS as exc:
        raise translate_sdk_error(exc, "PayPal capture failed") from exc

    captured = to_wire_dict(result.body) or {}
    # PayPal's own documented fee/net breakdown for this capture
    # (seller_receivable_breakdown), present on the SDK's PaymentsCapture
    # model and confirmed live against our own sandbox data - see the
    # paypal-server-sdk==2.4.0 bug report this followed up on, which turned
    # out not to reproduce here. "Not available for transactions that are
    # in pending state" per PayPal's own model docs, so it's genuinely
    # absent (not a bug) whenever a capture doesn't complete synchronously.
    breakdown = captured.get("seller_receivable_breakdown") or {}
    return {
        "capture_id": captured.get("id"),
        "status": captured.get("status"),
        "amount": _amount_value(captured.get("amount")),
        "currency": (captured.get("amount") or {}).get("currency_code"),
        "paypal_fee": _amount_value(breakdown.get("paypal_fee")),
        "net_amount": _amount_value(breakdown.get("net_amount")),
        "raw_status_code": result.status_code,
    }


async def void_authorization(authorization_id: str) -> dict:
    # Voiding doesn't move money and PayPal's own authorization-state rules
    # already make a repeat void a no-op/error rather than a duplicate
    # side effect, so this is lower risk than capture/authorize. Still send
    # a deterministic key, matching PayPal's general "recommended for all
    # POST and PUT calls" guidance and this file's other mutating calls.
    client = get_paypal_client()
    try:
        result = client.payments.void_payment({
            "authorization_id": authorization_id,
            "prefer": RETURN_REPRESENTATION,
            "paypal_request_id": f"auctara-void-{authorization_id}",
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
