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
                },
                "required": ["merchant", "amount", "currency", "category", "reason", "source_url"],
            },
        },
    },
]
