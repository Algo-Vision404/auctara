"""LLM-facing tool definitions.

Only research/proposal tools are exposed to the model. Policy evaluation and
PayPal execution are deliberately NOT callable by the LLM — they are invoked
only by the deterministic orchestrator after the model has finished.
"""
from __future__ import annotations

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "channel3_search_products",
            "description": (
                "Search Channel3's real-time catalog (100M+ products across online "
                "retailers) for structured purchase candidates. Returns live price, "
                "retailer domain, availability, and a buy URL directly — no page "
                "scraping needed. PREFER this over search_web/fetch_page whenever the "
                "task is to buy a physical or commercially-listed product. Only fall "
                "back to search_web if this returns no relevant candidates (e.g. a "
                "software subscription or service Channel3 doesn't carry)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to shop for, e.g. 'USB podcast microphone'."},
                    "max_price": {"type": "number", "description": "Optional maximum price in USD to filter by."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the live web for real products, merchants, and prices.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Specific search query."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": (
                "Fetch and read the real text content of a specific URL (e.g. a pricing "
                "page found via search_web). Use this when search result snippets don't "
                "contain enough detail, especially the actual price."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "A URL returned by search_web."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exchange_rate",
            "description": "Get the live exchange rate from a currency to USD.",
            "parameters": {
                "type": "object",
                "properties": {
                    "currency": {"type": "string", "description": "3-letter ISO currency code, e.g. EUR"},
                },
                "required": ["currency"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_purchase_proposal",
            "description": (
                "Submit the single best purchase recommendation found during research. "
                "This does NOT execute a purchase — it only creates a proposal that a "
                "separate deterministic policy engine will evaluate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "merchant": {"type": "string"},
                    "product_name": {"type": "string"},
                    "amount": {"type": "number", "description": "Price in `currency`."},
                    "currency": {"type": "string", "description": "3-letter ISO currency code"},
                    "category": {
                        "type": "string",
                        "description": "One of: software, office, business, hardware, travel, "
                        "marketing, subscriptions, other",
                    },
                    "reason": {"type": "string", "description": "Why this option was chosen."},
                    "source_url": {"type": "string", "description": "URL of the listing found."},
                    "image_url": {
                        "type": "string",
                        "description": "Product image URL, if this candidate came from channel3_search_products.",
                    },
                    "retailer": {
                        "type": "string",
                        "description": "Retailer domain, if this candidate came from channel3_search_products.",
                    },
                    "channel3_product_id": {
                        "type": "string",
                        "description": "Channel3 product id, if this candidate came from channel3_search_products.",
                    },
                },
                "required": ["merchant", "amount", "currency", "category", "reason", "source_url"],
            },
        },
    },
]
