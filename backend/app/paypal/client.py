"""PayPal client: built on PayPal's own official, APIMatic-generated
`paypal-server-sdk` (import package `paypalserversdk`), not a hand-rolled
OAuth2 + httpx integration.

The SDK (not this module) owns the OAuth2 client-credentials token fetch,
caching and refresh, request retries, and typed error exceptions. This
module is a thin wrapper that:

  * builds the one long-lived `PaypalServersdkClient` AgentAuth uses, from
    `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` / `PAYPAL_ENVIRONMENT`
  * translates whatever the SDK raises (`ApiException` and its typed
    subclasses, `AuthValidationException` for bad credentials, `requests`
    transport errors) into AgentAuth's own `PayPalError`, keeping PayPal's
    real error detail attached rather than swallowing it
  * exposes `to_wire_dict`, a generic unwrapper that turns an SDK response
    model back into the same plain snake_case dict PayPal's raw JSON uses
    (every generated model's `_names` map is an identity map for this API,
    so this round-trips losslessly), so the rest of the codebase keeps
    working with plain dicts

No transaction result is ever synthesized here. Every call either returns
PayPal's real response or raises PayPalError with the real detail attached.
"""
from __future__ import annotations

from typing import Any, Optional

import requests
from apimatic_core.exceptions.auth_validation_exception import (
    AuthValidationException,
)
from paypalserversdk.configuration import Environment
from paypalserversdk.exceptions.api_exception import ApiException
from paypalserversdk.http.auth.o_auth_2 import ClientCredentialsAuthCredentials
from paypalserversdk.paypal_serversdk_client import PaypalServersdkClient

from app.config import get_settings

# Every exception type a call through the SDK can raise that represents a
# real interaction with (or failure to reach) PayPal. See the SDK's own
# python-error-handling guidance: ApiException (and typed subclasses) for
# non-2xx responses, AuthValidationException for credentials the auth
# scheme itself rejects before a request is even sent, and the underlying
# `requests` transport errors for anything that never got an HTTP response.
PAYPAL_SDK_EXCEPTIONS = (ApiException, AuthValidationException, requests.exceptions.RequestException)


class PayPalError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


def translate_sdk_error(exc: Exception, context: str) -> PayPalError:
    """Turn any exception raised by an SDK call into a PayPalError, carrying
    PayPal's own error detail (name/message/debug_id/details) through rather
    than discarding it."""
    if isinstance(exc, ApiException):
        detail = {
            "name": getattr(exc, "name", None),
            "message": getattr(exc, "message", None) or exc.reason,
            "debug_id": getattr(exc, "debug_id", None),
            "details": _error_details_to_list(getattr(exc, "details", None)),
        }
        message = detail["message"] or exc.reason
        return PayPalError(
            f"{context} (HTTP {exc.response_code}): {message}",
            status_code=exc.response_code,
            detail=detail,
        )
    if isinstance(exc, AuthValidationException):
        return PayPalError(f"{context}: PayPal rejected the configured credentials ({exc}).")
    if isinstance(exc, requests.exceptions.RequestException):
        return PayPalError(f"{context}: could not reach PayPal ({exc}).")
    return PayPalError(f"{context}: {exc}")


def _error_details_to_list(details: Any) -> Optional[list]:
    if not details:
        return None
    out = []
    for d in details:
        out.append({
            "field": getattr(d, "field", None),
            "issue": getattr(d, "issue", None),
            "description": getattr(d, "description", None),
        })
    return out


def to_wire_dict(obj: Any) -> Any:
    """Recursively convert an SDK model instance (or a list/dict of them)
    back into the plain nested dict PayPal's raw JSON uses, via each
    model's own `_names` map (python-attribute -> wire key). PayPal's API is
    already snake_case end to end, so every generated `_names` map on this
    SDK is an identity map, so this is a lossless round trip, not a guess."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [to_wire_dict(item) for item in obj]
    if isinstance(obj, dict):
        return {key: to_wire_dict(value) for key, value in obj.items()}
    names = getattr(obj, "_names", None)
    if names:
        return {
            wire_name: to_wire_dict(getattr(obj, py_attr))
            for py_attr, wire_name in names.items()
            if hasattr(obj, py_attr)
        }
    return obj


def _build_client() -> PaypalServersdkClient:
    settings = get_settings()
    if not (settings.paypal_client_id and settings.paypal_client_secret):
        raise PayPalError(
            "PayPal is not configured. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET."
        )
    environment = (
        Environment.PRODUCTION if settings.paypal_environment.lower() == "live" else Environment.SANDBOX
    )
    return PaypalServersdkClient(
        environment=environment,
        client_credentials_auth_credentials=ClientCredentialsAuthCredentials(
            o_auth_client_id=settings.paypal_client_id,
            o_auth_client_secret=settings.paypal_client_secret,
        ),
        timeout=20,
    )


_client_singleton: Optional[PaypalServersdkClient] = None


def get_paypal_client() -> PaypalServersdkClient:
    """Return the shared SDK client. Built once and reused for the process
    lifetime: the SDK's own client-initialization guidance says a fresh client
    per call discards connection pooling and the cached OAuth2 token."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = _build_client()
    return _client_singleton


def reset_paypal_client() -> None:
    """Force the next get_paypal_client() call to rebuild the SDK client
    from current settings. Used by tests and after credential rotation."""
    global _client_singleton
    _client_singleton = None
