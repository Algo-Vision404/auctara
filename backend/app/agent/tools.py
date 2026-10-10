"""LLM-facing tool definitions.

Only research/proposal tools are exposed to the model. Policy evaluation and
PayPal execution are deliberately NOT callable by the LLM. They are invoked
only by the deterministic orchestrator after the model has finished.
"""
from __future__ import annotations

from app.agent.categories import PURCHASE_CATEGORIES

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "channel3_search_products",
            "description": (
                "Search Channel3's real-time catalog (100M+ products across online "
                "retailers) for structured purchase candidates. Returns live price, "
                "retailer domain, availability, and a buy URL directly, with no page "
                "scraping needed. PREFER this over search_web/fetch_page whenever the "
                "task is to buy a PHYSICAL, shippable retail product. Channel3 only ever "
                "carries real inventory from real online retailers - it has NEVER carried "
                "software, SaaS, subscriptions, licenses, cloud/API plans, or any other "
                "purely digital good, and never will. For any of those, skip this tool "
                "entirely and use search_web/fetch_page from the start; calling this for a "
                "digital purchase will be rejected and only wastes a turn."
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
                "This does NOT execute a purchase. It only creates a proposal that a "
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
                        # A hard enum, not just a description hint: the policy
                        # engine's allowed/blocked category lists are only
                        # ever expressed in this exact fixed vocabulary (see
                        # categories.py), so if this were left as free text
                        # the model could emit a category (e.g. "food") that
                        # no policy could ever have been configured to allow,
                        # causing a genuinely in-scope, correctly-researched
                        # purchase to be wrongly blocked for a reason no
                        # human ever had a chance to anticipate or fix.
                        "enum": PURCHASE_CATEGORIES,
                        "description": f"One of: {', '.join(PURCHASE_CATEGORIES)}",
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
    {
        "type": "function",
        "function": {
            "name": "decline_out_of_scope_task",
            "description": (
                "Decline to research or propose anything because this task has no "
                "reasonable connection to the agent's stated purpose and standing "
                "directive. Call this immediately instead of researching or calling "
                "create_purchase_proposal whenever the task is clearly outside what "
                "this agent was delegated to do (for example, a SaaS/subscription "
                "procurement agent being asked to buy snacks, entertainment, or "
                "anything unrelated to its assigned role)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why this task is outside the agent's assigned scope.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
]
