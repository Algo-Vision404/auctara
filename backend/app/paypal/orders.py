"""PayPal Orders v2 flow, using intent=AUTHORIZE for true two-phase safety:

  create_order()   -> places a hold (authorization) for the proposed amount
  get_order()      -> retrieve current state (used to verify before capture)
  capture_authorization() -> release the hold and take the money
  void_authorization()    -> release the hold without charging

If a sandbox test card is configured (PAYPAL_TEST_CARD_*), the order is
created with a direct card payment_source so the authorization completes
synchronously (no buyer browser redirect needed) — this is the path used
for an agent acting autonomously on a payment method already on file.
Otherwise a standard "approve" link is returned, and the frontend sends the
shopper to PayPal Sandbox to approve the order like a normal checkout.
"""
from __future__ import annotations

from app.config import get_settings
from app.paypal.client import PayPalError, get_paypal_client


def _card_payment_source() -> dict | None:
    s = get_settings()
    if not (s.paypal_test_card_number and s.paypal_test_card_expiry and s.paypal_test_card_cvv):
        return None
    return {
        "card": {
            "number": s.paypal_test_card_number,
            "expiry": s.paypal_test_card_expiry,
            "security_code": s.paypal_test_card_cvv,
            "name": s.paypal_test_card_name or "AgentAuth Agent",
        }
    }


async def create_order(amount: float, currency: str, description: str,
                        return_url: str, cancel_url: str, custom_id: str) -> dict:
    client = get_paypal_client()
    body: dict = {
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "custom_id": custom_id,
                "description": description[:127] if description else "AgentAuth purchase",
                "amount": {"currency_code": currency.upper(), "value": f"{amount:.2f}"},
            }
        ],
        "application_context": {
            "return_url": return_url,
            "cancel_url": cancel_url,
            "brand_name": "AgentAuth",
            "shipping_preference": "NO_SHIPPING",
            "user_action": "PAY_NOW",
        },
    }

    card_source = _card_payment_source()
    if card_source:
        body["payment_source"] = card_source

    result = await client.request("POST", "/v2/checkout/orders", json_body=body)
    return _summarize_order(result)


async def get_order(order_id: str) -> dict:
    client = get_paypal_client()
    result = await client.request("GET", f"/v2/checkout/orders/{order_id}")
    return _summarize_order(result)


async def authorize_order(order_id: str) -> dict:
    """Used after a buyer has approved the order via the redirect flow."""
    client = get_paypal_client()
    result = await client.request("POST", f"/v2/checkout/orders/{order_id}/authorize")
    return _summarize_order(result)


async def capture_authorization(authorization_id: str) -> dict:
    client = get_paypal_client()
    result = await client.request(
        "POST", f"/v2/payments/authorizations/{authorization_id}/capture",
        json_body={},
    )
    return {
        "capture_id": result.get("id"),
        "status": result.get("status"),
        "amount": _amount_value(result.get("amount")),
        "currency": (result.get("amount") or {}).get("currency_code"),
        "raw_status_code": result.get("status_code"),
    }


async def void_authorization(authorization_id: str) -> dict:
    client = get_paypal_client()
    result = await client.request("POST", f"/v2/payments/authorizations/{authorization_id}/void")
    return {"voided": True, "raw": result}


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
