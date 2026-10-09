"""Natural language -> structured financial policy.

The model only drafts a suggestion; it never writes to the database or
activates anything. The user must explicitly review and activate the
resulting policy via the API/UI.
"""
from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from app.agent.categories import PURCHASE_CATEGORIES
from app.agent.llm_errors import NOT_CONFIGURED_MESSAGE, humanize_llm_error
from app.config import get_settings

logger = logging.getLogger("agentauth.policy_drafting")

DRAFT_SYSTEM_PROMPT = f"""You convert a user's natural-language delegation \
instructions into a strict JSON financial policy object for an AI purchasing \
agent. Be conservative: if the user doesn't mention a limit, choose a sensible \
modest default. Always return valid JSON matching exactly this shape:

{{
  "agent_name": string,
  "agent_purpose": string,
  "max_transaction_amount": number,
  "approval_threshold": number,
  "daily_limit": number,
  "monthly_limit": number,
  "velocity": {{"max_transactions": integer, "window_minutes": integer}},
  "price_variance_tolerance": number (0-1, default 0.05),
  "blocked_categories": [string],
  "allowed_categories": [string]
}}

Rules:
- approval_threshold is the amount the agent can spend WITHOUT asking a human.
- max_transaction_amount is the absolute ceiling. Anything above it must be \
blocked outright, even with approval. It should be >= approval_threshold. If \
the user does not imply a hard ceiling, set it to 1.5x the approval_threshold.
- allowed_categories is the single most important scoping control you set: \
when it is non-empty, the agent can ONLY ever purchase in those exact \
categories, no matter what it is later asked to buy. The purchasing agent \
always classifies what it buys into one of exactly these categories: \
{', '.join(PURCHASE_CATEGORIES)}. Pick every category from that exact list \
(lowercase, verbatim) that is a genuine, direct fit for the purpose the user \
described, and put them in allowed_categories. For example, "manage our \
SaaS subscriptions" implies ["software", "subscriptions"], not every \
category: it must NOT also include "travel" or "other" just because they \
exist in the list. This is what actually stops a narrowly-scoped agent from \
being used for something unrelated later (like buying snacks or travel) even \
if that later request looks small, cheap, or easy to satisfy: it is \
rejected deterministically by category, before any AI judgment call is \
involved again.
- Only leave allowed_categories empty if the user's own instructions \
describe broad, general-purpose purchasing authority across categories \
(e.g. "handle all company purchasing" or "buy anything the team needs"), \
never as a default when the purpose is actually narrow.
- blocked_categories is a secondary, explicit exclusion list on top of \
allowed_categories (e.g. the user says "never buy gambling or crypto"). Use \
it for named exclusions the user actually stated; it does not need to \
duplicate what allowed_categories already excludes by omission.
- Respond with JSON only, no prose, no markdown fences.
"""



class PolicyDraftError(Exception):
    pass


async def draft_policy_from_text(instructions: str) -> dict:
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise PolicyDraftError(NOT_CONFIGURED_MESSAGE)

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
            # The output is always a small, bounded JSON object (a handful of
            # numbers, two short strings, and a couple of short category
            # lists), never more than a few hundred tokens in practice. Left
            # unset, the client defaults to the model's own max completion
            # tokens (16384 for gpt-4o-mini), which this call never needs and
            # which can fail outright on an account whose remaining balance
            # covers less than that ceiling, even though it easily covers
            # what this request actually produces.
            max_tokens=1024,
            response_format={"type": "json_object"},
            # Same fix as the main research loop: some free/reasoning-capable
            # OpenRouter models spend the whole token budget on invisible
            # chain-of-thought by default, which can truncate this call
            # before it ever emits the actual JSON object. This call only
            # ever needs a small structured result, never visible reasoning.
            extra_body={"reasoning": {"enabled": False}},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI policy drafting request failed")
        raise PolicyDraftError(humanize_llm_error(exc)) from exc

    content = response.choices[0].message.content
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.exception("AI returned an unparseable policy draft: %r", content)
        raise PolicyDraftError(
            "The AI couldn't produce a usable policy from that description. Please try rephrasing it."
        ) from exc

    required = ["max_transaction_amount", "approval_threshold", "daily_limit", "monthly_limit"]
    missing = [f for f in required if f not in data]
    if missing:
        logger.warning("AI policy draft missing required fields: %s", missing)
        raise PolicyDraftError(
            "The AI's policy draft was missing some required limits. Please try rephrasing your instructions "
            "with clearer spending limits."
        )

    data.setdefault("velocity", {"max_transactions": 5, "window_minutes": 60})
    data.setdefault("price_variance_tolerance", 0.05)
    data.setdefault("blocked_categories", [])
    data.setdefault("allowed_categories", [])
    data.setdefault("agent_name", "New Agent")
    data.setdefault("agent_purpose", instructions[:140])
    return data
