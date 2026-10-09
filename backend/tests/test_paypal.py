"""PayPal integration tests using mocked SDK controller responses (per spec:
unit tests may mock PayPal; the real app always calls the real Sandbox API
through PayPal's official `paypal-server-sdk`).

Responses are built with the SDK's own model classes (`Order.from_dictionary`,
etc.) from plain PayPal-shaped JSON, so these tests also exercise the real
`to_wire_dict` unwrapper in app.paypal.client, not just orders.py's own
summarizing logic.
"""
import pytest

from paypalserversdk.exceptions.error_exception import ErrorException
from paypalserversdk.models.captured_payment import CapturedPayment
from paypalserversdk.models.order import Order
from paypalserversdk.models.payment_authorization import PaymentAuthorization

from app.paypal import orders as paypal_orders
from app.paypal.client import PayPalError


class FakeApiResponse:
    """Stands in for apimatic_core's ApiResponse envelope: body + status_code."""

    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code


class FakeHttpResponse:
    """Stands in for the raw HttpResponse an ApiException wraps."""

    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.reason_phrase = ""
        self.headers = {}
        self.request = None


class FakeOrdersController:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def create_order(self, options):
        self.calls.append(("create_order", options))
        return self.responses["create_order"]

    def get_order(self, options):
        self.calls.append(("get_order", options))
        return self.responses["get_order"]

    def authorize_order(self, options):
        self.calls.append(("authorize_order", options))
        return self.responses["authorize_order"]


class FakePaymentsController:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def capture_authorized_payment(self, options):
        self.calls.append(("capture_authorized_payment", options))
        return self.responses["capture_authorized_payment"]

    def void_payment(self, options):
        self.calls.append(("void_payment", options))
        return self.responses["void_payment"]


class FakeClient:
    def __init__(self, order_responses=None, payment_responses=None):
        self.orders = FakeOrdersController(order_responses)
        self.payments = FakePaymentsController(payment_responses)


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
    fake = FakeClient(order_responses={
        "create_order": FakeApiResponse(Order.from_dictionary(ORDER_CREATED_WITH_AUTH)),
    })
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    result = await paypal_orders.create_order(
        amount=63.99, currency="USD", description="Test", return_url="https://x/return",
        cancel_url="https://x/cancel", custom_id="tx_1",
    )
    assert result["order_id"] == "ORDER123"
    assert result["authorization_id"] == "AUTH123"
    assert result["authorized_amount"] == 63.99

    # The SDK's typed OrderRequest model made it through, not a raw dict.
    _, options = fake.orders.calls[0]
    assert options["body"].intent == "AUTHORIZE"
    assert options["body"].purchase_units[0].custom_id == "tx_1"


@pytest.mark.asyncio
async def test_create_order_requires_buyer_approval(monkeypatch):
    fake = FakeClient(order_responses={
        "create_order": FakeApiResponse(Order.from_dictionary(ORDER_CREATED_NO_AUTH)),
    })
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    result = await paypal_orders.create_order(
        amount=63.99, currency="USD", description="Test", return_url="https://x/return",
        cancel_url="https://x/cancel", custom_id="tx_1",
    )
    assert result["authorization_id"] is None
    assert result["approve_url"] == "https://sandbox.paypal.com/approve/ORDER456"


@pytest.mark.asyncio
async def test_capture_authorization(monkeypatch):
    fake = FakeClient(payment_responses={
        "capture_authorized_payment": FakeApiResponse(CapturedPayment.from_dictionary(CAPTURE_RESPONSE)),
    })
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    result = await paypal_orders.capture_authorization("AUTH123")
    assert result["capture_id"] == "CAPTURE789"
    assert result["status"] == "COMPLETED"
    assert result["amount"] == 63.99


@pytest.mark.asyncio
async def test_void_authorization(monkeypatch):
    fake = FakeClient(payment_responses={
        "void_payment": FakeApiResponse(
            PaymentAuthorization.from_dictionary({"id": "AUTH123", "status": "VOIDED"})
        ),
    })
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    result = await paypal_orders.void_authorization("AUTH123")
    assert result["voided"] is True


@pytest.mark.asyncio
async def test_create_order_translates_api_exception(monkeypatch):
    """A real PayPal error (e.g. a malformed request) must surface as our own
    PayPalError, with PayPal's actual error detail attached. Never silently
    swallowed or turned into a fake success."""
    error_body = '{"name": "INVALID_REQUEST", "message": "Amount mismatch", "debug_id": "abc123"}'

    def boom(options):
        raise ErrorException("Request is not well-formed", FakeHttpResponse(400, error_body))

    fake = FakeClient()
    fake.orders.create_order = boom
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    with pytest.raises(PayPalError) as exc_info:
        await paypal_orders.create_order(
            amount=63.99, currency="USD", description="Test", return_url="https://x/return",
            cancel_url="https://x/cancel", custom_id="tx_1",
        )

    err = exc_info.value
    assert err.status_code == 400
    assert err.detail["name"] == "INVALID_REQUEST"
    assert err.detail["debug_id"] == "abc123"


@pytest.mark.asyncio
async def test_capture_authorization_without_mock_response_is_unchanged(monkeypatch):
    """The default (every normal transaction) path must never attach a
    PayPal-Mock-Response option - a real capture, exactly as before this
    feature existed."""
    fake = FakeClient(payment_responses={
        "capture_authorized_payment": FakeApiResponse(CapturedPayment.from_dictionary(CAPTURE_RESPONSE)),
    })
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    await paypal_orders.capture_authorization("AUTH123")

    _, options = fake.payments.calls[0]
    assert "paypal_mock_response" not in options


@pytest.mark.asyncio
async def test_capture_authorization_with_negative_test_attaches_mock_header(monkeypatch):
    """Opt-in sandbox QA hook: passing one of PayPal's own documented
    negative-testing codes must be forwarded to the SDK as the real
    PayPal-Mock-Response header value it expects, in PayPal's documented
    JSON shape."""
    fake = FakeClient(payment_responses={
        "capture_authorized_payment": FakeApiResponse(CapturedPayment.from_dictionary(CAPTURE_RESPONSE)),
    })
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    await paypal_orders.capture_authorization("AUTH123", mock_response="INSTRUMENT_DECLINED")

    _, options = fake.payments.calls[0]
    assert options["paypal_mock_response"] == '{"mock_application_codes": "INSTRUMENT_DECLINED"}'


@pytest.mark.asyncio
async def test_capture_authorization_negative_test_surfaces_as_real_paypal_error(monkeypatch):
    """When PayPal's own sandbox genuinely declines a mocked capture, that
    must surface as a real PayPalError with PayPal's real error detail,
    exactly like any other real PayPal rejection - not a fabricated result."""
    error_body = (
        '{"name": "UNPROCESSABLE_ENTITY", "message": "The requested action could not be completed.", '
        '"debug_id": "neg-test-1", "details": [{"issue": "INSTRUMENT_DECLINED"}]}'
    )

    def boom(options):
        assert options["paypal_mock_response"] == '{"mock_application_codes": "INSTRUMENT_DECLINED"}'
        raise ErrorException("Unprocessable", FakeHttpResponse(422, error_body))

    fake = FakeClient()
    fake.payments.capture_authorized_payment = boom
    monkeypatch.setattr(paypal_orders, "get_paypal_client", lambda: fake)

    with pytest.raises(PayPalError) as exc_info:
        await paypal_orders.capture_authorization("AUTH123", mock_response="INSTRUMENT_DECLINED")

    err = exc_info.value
    assert err.status_code == 422
    assert err.detail["name"] == "UNPROCESSABLE_ENTITY"
