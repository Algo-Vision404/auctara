"""Live exchange rate lookups. Never hard-coded, never cached silently stale
beyond a short TTL, and failures are surfaced rather than papered over."""
from __future__ import annotations

import logging
import time

import httpx

from app.config import get_settings

logger = logging.getLogger("agentauth.exchange")


class ExchangeRateError(Exception):
    pass


_cache: dict = {"fetched_at": 0.0, "rates": None, "base": None}
_TTL_SECONDS = 300


async def get_rates() -> dict:
    now = time.time()
    if _cache["rates"] and (now - _cache["fetched_at"]) < _TTL_SECONDS:
        return _cache["rates"]

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(settings.exchange_rate_api_url)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Exchange-rate service unavailable: %s", exc)
        raise ExchangeRateError(
            "Currency conversion is temporarily unavailable. Please try again shortly."
        ) from exc

    if data.get("result") != "success":
        logger.warning("Exchange-rate service returned an error: %s", data)
        raise ExchangeRateError(
            "Currency conversion is temporarily unavailable. Please try again shortly."
        )

    _cache["rates"] = data
    _cache["fetched_at"] = now
    _cache["base"] = data.get("base_code")
    return data


async def convert(amount: float, from_currency: str, to_currency: str = "USD") -> float:
    if from_currency.upper() == to_currency.upper():
        return amount
    data = await get_rates()
    rates = data.get("rates", {})
    if from_currency.upper() not in rates or to_currency.upper() not in rates:
        raise ExchangeRateError(f"Unsupported currency pair {from_currency}->{to_currency}")
    usd_amount = amount / rates[from_currency.upper()]
    return usd_amount * rates[to_currency.upper()]
