"""Natural language -> structured financial policy.

The model only drafts a suggestion; it never writes to the database or
activates anything. The user must explicitly review and activate the
resulting policy via the API/UI.
"""
from __future__ import annotations

import json

from openai import AsyncOpenAI

from app.config import get_settings

DRAFT_SYSTEM_PROMPT = """You convert a user's natural-language delegation \
instructions into a strict JSON financial policy object for an AI purchasing \
agent. Be conservative: if the user doesn't mention a limit, choose a sensible \
modest default. Always return valid JSON matching exactly this shape:

{
  "agent_name": string,
  "agent_purpose": string,
  "max_transaction_amount": number,
  "approval_threshold": number,
  "daily_limit": number,
  "monthly_limit": number,
  "velocity": {"max_transactions": integer, "window_minutes": integer},
  "price_variance_tolerance": number (0-1, default 0.05),
  "blocked_categories": [string],
  "allowed_categories": [string]
}

Rules:
- approval_threshold is the amount the agent can spend WITHOUT asking a human.
- max_transaction_amount is the absolute ceiling — anything above it must be \
blocked outright, even with approval. It should be >= approval_threshold. If \
the user does not imply a hard ceiling, set it to 1.5x the approval_threshold.
- allowed_categories may be empty (meaning: any category not blocked is ok).
- Respond with JSON only, no prose, no markdown fences.
"""


class PolicyDraftError(Exception):
    pass


async def draft_policy_from_text(instructions: str) -> dict:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise PolicyDraftError("OpenRouter is not configured. Set OPENROUTER_API_KEY.")

    client = AsyncOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers={"HTTP-Referer": settings.frontend_url or "http://localhost:3000", "X-Title": "AgentAuth"},
    )

    try:
        response = await client.chat.completions.create(
            model=settings.openrouter_model,
            messages=[
                {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
                {"role": "user", "content": instructions},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # noqa: BLE001
        raise PolicyDraftError(f"AI policy drafting failed: {exc}") from exc

    content = response.choices[0].message.content
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        raise PolicyDraftError(f"AI returned an unparseable policy: {exc}") from exc

    required = ["max_transaction_amount", "approval_threshold", "daily_limit", "monthly_limit"]
    missing = [f for f in required if f not in data]
    if missing:
        raise PolicyDraftError(f"AI policy draft missing required fields: {missing}")

    data.setdefault("velocity", {"max_transactions": 5, "window_minutes": 60})
    data.setdefault("price_variance_tolerance", 0.05)
    data.setdefault("blocked_categories", [])
    data.setdefault("allowed_categories", [])
    data.setdefault("agent_name", "New Agent")
    data.setdefault("agent_purpose", instructions[:140])
    return data
