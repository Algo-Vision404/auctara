"""PayPal REST API client: OAuth token handling with reuse/refresh.

Talks to the real PayPal Sandbox (or live, if configured) REST API.
No transaction result is ever synthesized here — every method either
returns PayPal's real response or raises PayPalError with the real
error detail attached.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from app.config import get_settings


class PayPalError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class PayPalClient:
    def __init__(self):
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    def _configured(self) -> bool:
        s = get_settings()
        return bool(s.paypal_client_id and s.paypal_client_secret)

    async def _get_token(self) -> str:
        settings = get_settings()
        if not self._configured():
            raise PayPalError(
                "PayPal is not configured. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET."
            )

        now = time.time()
        if self._token and now < self._token_expiry - 30:
            return self._token

        url = f"{settings.paypal_base_url}/v1/oauth2/token"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    data={"grant_type": "client_credentials"},
                    auth=(settings.paypal_client_id, settings.paypal_client_secret),
                    headers={"Accept": "application/json", "Accept-Language": "en_US"},
                )
        except httpx.HTTPError as exc:
            raise PayPalError(f"PayPal authentication failed: {exc}") from exc

        if resp.status_code != 200:
            raise PayPalError(
                f"PayPal authentication failed (HTTP {resp.status_code})",
                status_code=resp.status_code,
                detail=_safe_json(resp),
            )

        data = resp.json()
        self._token = data["access_token"]
        self._token_expiry = now + float(data.get("expires_in", 300))
        return self._token

    async def request(self, method: str, path: str, json_body: dict | None = None,
                       extra_headers: dict | None = None) -> dict:
        settings = get_settings()
        token = await self._get_token()
        url = f"{settings.paypal_base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        if extra_headers:
            headers.update(extra_headers)

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.request(method, url, json=json_body, headers=headers)
        except httpx.TimeoutException as exc:
            raise PayPalError(f"PayPal request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise PayPalError(f"PayPal request failed: {exc}") from exc

        if resp.status_code >= 400:
            raise PayPalError(
                f"PayPal API error (HTTP {resp.status_code})",
                status_code=resp.status_code,
                detail=_safe_json(resp),
            )

        if resp.status_code == 204 or not resp.content:
            return {"status_code": resp.status_code}

        return resp.json()


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text


_client_singleton: Optional[PayPalClient] = None


def get_paypal_client() -> PayPalClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = PayPalClient()
    return _client_singleton
