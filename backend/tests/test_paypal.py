"""PayPal integration tests using mocked HTTP responses (per spec: unit tests
may mock PayPal; the real app always calls the real Sandbox API)."""
import pytest

from app.paypal import orders as paypal_orders
from app.paypal.client import PayPalClient


class FakeClient(PayPalClient):
    def __init__(self, responses):
        super().__init__()
        self.responses = responses
        self.calls = []

    async def request(self, method, path, json_body=None, extra_headers=None):
        self.calls.append((method, path, json_body))
        key = (method, path.split("?")[0])
        for (m, p_prefix), resp in self.responses.items():
            if m == method and path.startswith(p_prefix):
                return resp
        raise AssertionError(f"Unexpected call {method} {path}")


ORDER_CREATED_WITH_AUTH = {
    "id": "ORDER123",
    "status": "COMPLETED",
    "links": [{"rel": "self", "href": "https://api/x"}],
    "purchase_units": [
        {
            "amount": {"currency_code": "USD", "value": "63.99"},
            "payments": {
                "authorizations": [
                    {"id": "AUTH123", "status": "CREATED", "amount": {"currency_code": "USD", "value": "63.99"}}
                ]
            },
        }
    ],
}

ORDER_CREATED_NO_AUTH = {
    "id": "ORDER456",
    "status": "PAYER_ACTION_REQUIRED",
    "links": [
        {"rel": "self", "href": "https://api/x"},
        {"rel": "approve", "href": "https://sandbox.paypal.com/approve/ORDER456"},
    ],
    "purchase_units": [{"amount": {"currency_code": "USD", "value": "63.99"}}],
}

CAPTURE_RESPONSE = {"id": "CAPTURE789", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "63.99"}}


@pytest.mark.asyncio
async def test_create_order_with_immediate_authorization(monkeypatch):
    fake = FakeClient({("POST", "/v2/checkout/orders"): ORDER_CREATED_WITH_AUTH})
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    result = await paypal_orders.create_order(
        amount=63.99, currency="USD", description="Test", return_url="https://x/return",
        cancel_url="https://x/cancel", custom_id="tx_1",
    )
    assert result["order_id"] == "ORDER123"
    assert result["authorization_id"] == "AUTH123"
    assert result["authorized_amount"] == 63.99


@pytest.mark.asyncio
async def test_create_order_requires_buyer_approval(monkeypatch):
    fake = FakeClient({("POST", "/v2/checkout/orders"): ORDER_CREATED_NO_AUTH})
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    result = await paypal_orders.create_order(
        amount=63.99, currency="USD", description="Test", return_url="https://x/return",
        cancel_url="https://x/cancel", custom_id="tx_1",
    )
    assert result["authorization_id"] is None
    assert result["approve_url"] == "https://sandbox.paypal.com/approve/ORDER456"


@pytest.mark.asyncio
async def test_capture_authorization(monkeypatch):
    fake = FakeClient({("POST", "/v2/payments/authorizations/AUTH123/capture"): CAPTURE_RESPONSE})
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    result = await paypal_orders.capture_authorization("AUTH123")
    assert result["capture_id"] == "CAPTURE789"
    assert result["status"] == "COMPLETED"
    assert result["amount"] == 63.99


@pytest.mark.asyncio
async def test_void_authorization(monkeypatch):
    fake = FakeClient({("POST", "/v2/payments/authorizations/AUTH123/void"): {"status_code": 204}})
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    result = await paypal_orders.void_authorization("AUTH123")
    assert result["voided"] is True
