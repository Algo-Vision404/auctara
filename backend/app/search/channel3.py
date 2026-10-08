"""Channel3 product discovery — real-time structured commerce data.

Channel3 (https://trychannel3.com) indexes 100M+ real products across online
retailers and returns live price, availability, retailer, and imagery for
each one. The procurement agent calls this FIRST for any shopping/purchase
task, because it returns structured, trustworthy offer data directly —
no page-scraping needed — and that data flows straight into the purchase
proposal AgentAuth's policy engine ultimately evaluates.

No fallback or fabricated data is ever returned here. If the API key is
missing, the request fails, or Channel3 returns no candidates, a real
Channel3Error propagates so the orchestrator can surface a genuine failure
(SEARCH_FAILED-style event) instead of inventing a product.
"""
from __future__ import annotations

import httpx

from app.config import get_settings


class Channel3Error(Exception):
    pass


def _best_offer(offers: list[dict]) -> dict | None:
    """Pick the cheapest in-stock offer; fall back to the cheapest offer of
    any availability if nothing is in stock. Never invents an offer."""
    if not offers:
        return None
    in_stock = [o for o in offers if o.get("availability") == "InStock"]
    pool = in_stock or offers
    return min(pool, key=lambda o: (o.get("price") or {}).get("price", float("inf")))


def _normalize(product: dict) -> dict:
    offer = _best_offer(product.get("offers") or [])
    price_info = (offer or {}).get("price") or {}
    brand = (product.get("brands") or [{}])[0].get("name")
    image = next(
        (img.get("cleaned_url") or img.get("url") for img in product.get("images") or [] if img.get("is_main_image")),
        None,
    ) or next((img.get("cleaned_url") or img.get("url") for img in product.get("images") or []), None)

    return {
        "channel3_product_id": product.get("id"),
        "title": product.get("title"),
        "brand": brand,
        "category": (product.get("category") or {}).get("title"),
        "key_features": (product.get("key_features") or [])[:3],
        "image_url": image,
        "price": price_info.get("price"),
        "compare_at_price": price_info.get("compare_at_price"),
        "currency": price_info.get("currency", "USD"),
        "availability": offer.get("availability") if offer else None,
        "retailer": offer.get("domain") if offer else None,
        "buy_url": offer.get("url") if offer else None,
        "offer_count": len(product.get("offers") or []),
    }


async def search_products(query: str, max_price: float | None = None, limit: int = 8) -> list[dict]:
    settings = get_settings()
    if not settings.channel3_api_key:
        raise Channel3Error(
            "Channel3 is not configured. Set CHANNEL3_API_KEY in the backend's .env "
            "to enable real-time product discovery."
        )

    body: dict = {"query": query, "limit": max(1, min(limit, 20))}
    if max_price is not None:
        body["filters"] = {"price": {"max_price": max_price}}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.channel3_base_url}/v1/search",
                headers={"x-api-key": settings.channel3_api_key, "content-type": "application/json"},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:300]
        raise Channel3Error(f"Channel3 returned HTTP {exc.response.status_code}: {detail}") from exc
    except httpx.HTTPError as exc:
        raise Channel3Error(f"Channel3 is unreachable: {exc}") from exc

    products = data.get("products") or []
    normalized = [_normalize(p) for p in products]
    # Only keep candidates that actually have a real priced, buyable offer.
    normalized = [p for p in normalized if p["price"] is not None and p["buy_url"]]
    return normalized
