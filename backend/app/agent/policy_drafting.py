"""Natural language -> structured financial policy.

The model only drafts a suggestion; it never writes to the database or
activates anything. The user must explicitly review and activate the
resulting policy via the API/UI.

Drafting is a short, bounded conversation, not a single blind guess: when
the user's instructions leave something materially important unresolved
(scope, budget, or a named exclusion that doesn't map onto this agent's
fixed category vocabulary), the model asks ONE short clarifying question
and the caller (the /agents/draft-policy route) pauses and hands it to the
human, exactly like the main research loop's NEEDS_INPUT pattern. The
conversation itself is just a plain list of messages the caller owns and
re-sends, grown by one answer each round - there is no server-side session
for this (unlike a real task/transaction), since no agent record exists yet
at draft time to hang that state off of.
"""
from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from app.agent.categories import PURCHASE_CATEGORIES
from app.agent.llm_errors import NOT_CONFIGURED_MESSAGE, humanize_llm_error
from app.config import get_settings

logger = logging.getLogger("agentauth.policy_drafting")

# A tighter cap than the main research loop's MAX_CLARIFICATION_ROUNDS (5):
# a human is sitting right here actively setting up an agent, not waiting on
# a real-world purchase decision days later, so a short back-and-forth is
# fine but an open-ended interrogation is not. After this many questions the
# model is told to stop asking and commit to its best reasonable
# assumptions instead - loudly, via "assumptions", never silently.
MAX_POLICY_CLARIFICATION_ROUNDS = 3

DRAFT_SYSTEM_PROMPT = f"""You convert a user's natural-language delegation \
instructions into a strict JSON financial policy object for an AI purchasing \
agent, through a short conversation rather than a single blind guess.

Every reply you give MUST be a single JSON object, one of exactly two shapes:

1. {{"type": "clarifying_question", "question": string}}
Use this when something you cannot responsibly guess would materially \
change the budget, the scope of what this agent may buy, or a named \
exclusion the user asked for. Ask exactly ONE short, plain, specific \
question - it is shown directly to the user verbatim. Never ask about \
something the instructions, or an earlier answer in this same \
conversation, already told you.

2. {{"type": "policy_draft", "draft": {{ ...the full policy object below... }}}}
Use this once you have enough information - either because the \
instructions were already clear, or because the user has now answered \
enough of your questions - or because you have already asked \
{MAX_POLICY_CLARIFICATION_ROUNDS} questions in this conversation and must \
stop asking and commit to your best reasonable assumption for anything \
still genuinely unclear.

The policy_draft object itself must match exactly this shape:
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
  "allowed_categories": [string],
  "assumptions": [string]
}}

Ask a clarifying question (do not guess) when:
- The scope is named only vaguely (e.g. "manage our SaaS subscriptions" \
without saying which tools, or whether this also covers discovering and \
buying NEW subscriptions versus only renewing existing ones). This changes \
both allowed_categories and what a normal-looking transaction amount even \
is.
- No limit of any kind is implied anywhere (not even roughly) for \
approval_threshold/max_transaction_amount/daily_limit/monthly_limit. A \
vague "manage expenses" with literally no number anywhere is worth one \
question; a merely imprecise one ("around a hundred bucks or so, a few \
thousand a month") is not - round it and move on without asking.
- The user's instructions don't make it obvious whether this agent should \
have broad purchasing authority across every category or be scoped to a \
handful. Defaulting allowed_categories to [] (unrestricted) when that is \
wrong is the single highest blast-radius mistake this draft can make, so \
if it is genuinely unclear, ask rather than default to unrestricted.
- The user names something to exclude (e.g. "never buy gambling or \
crypto") that is NOT one of this agent's fixed classification categories: \
{', '.join(PURCHASE_CATEGORIES)}. Tell them plainly, inside the question \
itself, that an exclusion like that can only ever be enforced as a \
best-effort text match against a proposal's merchant/product/reason (it \
cannot be a guaranteed category block, since the purchasing agent has no \
category for it), and confirm they still want it recorded that way - or \
ask if they actually meant one of the real categories instead.

Do NOT ask about anything else. Small, non-material details (exact cents, \
whether an obvious SaaS tool is "software" or "subscriptions", a velocity \
window) should just be filled in with a sensible default, never asked \
about. Never ask more than one question per reply, and never ask more than \
{MAX_POLICY_CLARIFICATION_ROUNDS} questions across the whole conversation.

Rules for the policy_draft itself, once you are ready to produce it:
- approval_threshold is the amount the agent can spend WITHOUT asking a human.
- max_transaction_amount is the absolute ceiling. Anything above it must be \
blocked outright, even with approval. It should be >= approval_threshold. If \
the user does not imply a hard ceiling, set it to 1.5x the approval_threshold.
- allowed_categories is the single most important scoping control you set: \
when it is non-empty, the agent can ONLY ever purchase in those exact \
categories, no matter what it is later asked to buy. The purchasing agent \
always classifies what it buys into one of exactly these categories: \
{', '.join(PURCHASE_CATEGORIES)}. Pick every category from that exact list \
(lowercase, verbatim) that is a genuine, direct fit for the purpose the \
user described, and put them in allowed_categories. For example, "manage \
our SaaS subscriptions" implies ["software", "subscriptions"], not every \
category: it must NOT also include "travel" or "other" just because they \
exist in the list. This is what actually stops a narrowly-scoped agent \
from being used for something unrelated later (like buying snacks or \
travel) even if that later request looks small, cheap, or easy to \
satisfy: it is rejected deterministically by category, before any AI \
judgment call is involved again.
- Only leave allowed_categories empty if the user's own instructions (or \
their answers to your questions) describe broad, general-purpose \
purchasing authority across categories (e.g. "handle all company \
purchasing" or "buy anything the team needs"), never as an unexamined \
default when the purpose is actually narrow.
- blocked_categories is a secondary, explicit exclusion list on top of \
allowed_categories. Put a genuine category name in it when the user names \
one of the fixed categories above; put a free-text term in it when they \
name something else (e.g. "gambling", "crypto") only AFTER you've \
confirmed with them, per the clarifying-question rule above, that they \
understand it will only ever be enforced as a best-effort text match.
- "assumptions" lists, in your own plain words, the handful of decisions \
you made that would actually matter to the person reading this - money \
ceilings and scope, never internal plumbing. Never write a field name \
(max_transaction_amount, velocity, price_variance_tolerance, daily_limit, \
etc.) - describe the real decision the way you'd say it out loud to the \
person. Skip routine technical defaults nobody would actually want to be \
told about (a standard velocity window, the default price tolerance) \
unless something in their own instructions makes that particular one \
unusual or worth flagging. Keep the list to only the few things that \
would genuinely change someone's mind if they disagreed - not a checklist \
of every field that happened to get a default.
  GOOD: "You didn't set a hard ceiling, so I capped any single purchase at \
$75 - 1.5x the $50 you said it can spend without asking you."
  GOOD: "No daily limit was mentioned, so I'm using your $2,000 monthly \
budget as the daily cap too, since nothing suggested it should be lower."
  BAD: "Set max_transaction_amount to 1.5x approval_threshold ($75) since \
user only specified a threshold, not a hard ceiling." (never name fields \
like this)
  BAD: "Set velocity defaults: max 10 transactions per 60 minutes." (this \
is routine plumbing nobody needs to approve - leave it out of the list \
entirely)
Leave assumptions empty only when literally every field was directly \
stated or already asked about. This is shown to the user before they \
activate anything, so make every item worth their actual attention, never \
generic filler and never implementation detail.
- Respond with JSON only, no prose, no markdown fences, and always one of \
the exact two shapes above - nothing else.
"""


class PolicyDraftError(Exception):
    pass


class PolicyNeedsClarification(Exception):
    """Raised when the drafting model asks a clarifying question instead of
    producing a final draft. `conversation` is the full transcript so far,
    INCLUDING the assistant's own question message - the caller (the API
    route) must hand this back unchanged, with the human's answer appended,
    to continue the same conversation."""

    def __init__(self, question: str, conversation: list[dict]):
        super().__init__(question)
        self.question = question
        self.conversation = conversation


def _client_and_settings():
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise PolicyDraftError(NOT_CONFIGURED_MESSAGE)
    client = AsyncOpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers={"HTTP-Referer": settings.frontend_url or "http://localhost:3000", "X-Title": "AgentAuth"},
    )
    return client, settings


async def draft_policy_step(conversation: list[dict]) -> dict:
    """Runs exactly one turn of the policy-drafting conversation.

    `conversation` is the full transcript so far - starting life as a
    single {"role": "user", "content": <the user's original instructions>}
    - and is owned entirely by the caller, the same split
    _run_research_loop uses for its own `messages`: this function has no
    memory between calls, all continuity lives in the list passed in.

    Returns the finished draft dict once the model is ready, or raises
    PolicyNeedsClarification so the caller can show the question to a
    human and call this again later with their answer appended.
    """
    client, settings = _client_and_settings()

    # How many questions this conversation has already asked, derived from
    # the transcript itself rather than a separate counter the caller would
    # have to thread through - there is nowhere stateful to keep one, since
    # no agent/DB row exists yet at draft time.
    rounds_asked = sum(1 for m in conversation if m.get("role") == "assistant")
    messages = [{"role": "system", "content": DRAFT_SYSTEM_PROMPT}, *conversation]
    if rounds_asked >= MAX_POLICY_CLARIFICATION_ROUNDS:
        messages.append({
            "role": "user",
            "content": (
                f"You have already asked {rounds_asked} clarifying questions, the most allowed. "
                "Do not ask another one. Respond now with the final policy_draft, making the most "
                "reasonable assumption for anything still unclear, and list each one in \"assumptions\"."
            ),
        })

    try:
        response = await client.chat.completions.create(
            model=settings.openrouter_model,
            messages=messages,
            temperature=0.1,
            # A clarifying question or a policy draft are both always a
            # small, bounded JSON object, never more than a few hundred
            # tokens in practice. Left unset, the client defaults to the
            # model's own max completion tokens (16384 for gpt-4o-mini),
            # which this call never needs and which can fail outright on an
            # account whose remaining balance covers less than that
            # ceiling, even though it easily covers what this request
            # actually produces.
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
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.exception("AI returned an unparseable policy draft reply: %r", content)
        raise PolicyDraftError(
            "The AI couldn't produce a usable policy from that description. Please try rephrasing it."
        ) from exc

    msg_type = parsed.get("type") if isinstance(parsed, dict) else None

    # Only honor a clarifying question while still under the round cap -
    # the forced final-answer nudge above already told the model not to
    # ask again, but a model that ignores that instruction must not be
    # allowed to stall this conversation forever. Falling through to the
    # draft-parsing path below means a round-cap-exceeding question gets
    # treated as an (almost certainly incomplete) draft attempt instead,
    # which fails loudly via the missing-fields check rather than looping.
    if msg_type == "clarifying_question" and rounds_asked < MAX_POLICY_CLARIFICATION_ROUNDS:
        question = str(parsed.get("question") or "").strip()
        if not question:
            raise PolicyDraftError(
                "The AI tried to ask a follow-up question but didn't actually say what it wanted to "
                "know. Please try rephrasing your instructions."
            )
        new_conversation = [*conversation, {"role": "assistant", "content": content}]
        raise PolicyNeedsClarification(question, new_conversation)

    draft = parsed.get("draft") if msg_type == "policy_draft" else parsed
    if not isinstance(draft, dict):
        logger.warning("AI policy draft reply had no usable draft object: %r", content)
        raise PolicyDraftError(
            "The AI couldn't produce a usable policy from that description. Please try rephrasing it."
        )

    required = ["max_transaction_amount", "approval_threshold", "daily_limit", "monthly_limit"]
    missing = [f for f in required if f not in draft]
    if missing:
        logger.warning("AI policy draft missing required fields: %s", missing)
        raise PolicyDraftError(
            "The AI's policy draft was missing some required limits. Please try rephrasing your instructions "
            "with clearer spending limits."
        )

    draft.setdefault("velocity", {"max_transactions": 5, "window_minutes": 60})
    draft.setdefault("price_variance_tolerance", 0.05)
    draft.setdefault("blocked_categories", [])
    draft.setdefault("allowed_categories", [])
    draft.setdefault("assumptions", [])
    draft.setdefault("agent_name", "New Agent")
    original_instructions = next((m.get("content", "") for m in conversation if m.get("role") == "user"), "")
    draft.setdefault("agent_purpose", original_instructions[:140])
    return draft


async def draft_policy_from_text(instructions: str) -> dict:
    """Convenience wrapper that starts a brand new drafting conversation
    from a single plain-language instructions string - kept so the common
    first call doesn't need to know the message-list shape. May still
    raise PolicyNeedsClarification on this very first call, exactly like
    any later one."""
    return await draft_policy_step([{"role": "user", "content": instructions}])
