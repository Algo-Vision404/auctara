"""Turn a raw OpenRouter/OpenAI SDK exception into a message a non-technical
end user can actually use, for every place an LLM call can fail: the
research/purchase loop and AI policy drafting.

Written with a bit of personality instead of flat corporate-speak - the
agent is "talking" about its own outage, not reciting a status page - while
still always landing on the real actionable point (what's actually wrong,
and that an administrator needs to fix it). Never mentions "OpenRouter", env
var names, dashboard URLs, raw HTTP status codes, or SDK exception text -
that's operator-facing detail that belongs in the logs, not the message a
user watching a task or chatting with an agent has to read. The full
original exception is always logged server-side first (logger.exception at
the call site, and this module's own logger.warning here), so nothing is
actually lost, only kept off the surface a user sees.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable, TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError

logger = logging.getLogger("agentauth.llm_errors")

T = TypeVar("T")

# Status codes worth a short automatic retry: 429 (rate limited) and any 5xx
# (the upstream provider itself having a momentary bad day). Everything else
# - 401 bad credentials, 402 out of credit, 400 bad request, etc. - will
# fail exactly the same way no matter how many times it's retried, so those
# are raised immediately instead of wasting time (and the user's patience)
# retrying something that can't succeed.
_TRANSIENT_STATUS_CODES = {429}


def _is_exhausted_daily_quota(exc: Exception) -> bool:
    """True for a 429 that is specifically OpenRouter's free-model *daily*
    request cap, not a brief per-minute/per-second burst limit. OpenRouter
    reports which kind of limit tripped in the error body's
    `metadata.limit_source` (e.g. "openrouter_free_tier_daily"), and
    separately exposes "X-RateLimit-Remaining": "0" when none are left.
    This distinction matters because a burst limit clears again within
    seconds (worth a short retry), while a daily cap only resets at a fixed
    time hours away - retrying it for a few seconds can never help and just
    delays surfacing the real problem.

    The OpenAI SDK's `exc.body` has been observed to hold either the inner
    error object directly (`{"message": ..., "metadata": {...}}`, what it
    actually returns in practice) or that object wrapped in an outer
    `{"error": {...}}` key (the shape of the raw HTTP response body) -
    both are checked so this keeps working either way.
    """
    if not isinstance(exc, APIStatusError) or exc.status_code != 429:
        return False
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else body
    metadata = error.get("metadata") if isinstance(error.get("metadata"), dict) else {}
    limit_source = str(metadata.get("limit_source") or "")
    message = str(error.get("message") or "")
    return "daily" in limit_source.lower() or "per-day" in message.lower()


def is_transient_llm_error(exc: Exception) -> bool:
    """True for the class of error worth a short automatic retry - a brief
    rate-limit burst, a 5xx from the upstream AI provider, or a
    dropped/timed out connection - as opposed to an error that will never
    succeed no matter how many times it's retried (bad credentials, no
    credit, a bad request, or a *daily* quota that's already hit zero and
    won't reset for hours)."""
    if _is_exhausted_daily_quota(exc):
        return False
    if isinstance(exc, APIStatusError):
        status = exc.status_code or 0
        return status in _TRANSIENT_STATUS_CODES or status >= 500
    return isinstance(exc, (APIConnectionError, APITimeoutError))


async def call_llm_with_retry(
    make_call: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
) -> T:
    """Run one LLM request (`make_call`, an async no-arg callable), retrying
    with a short exponential backoff when the failure looks transient. The
    rate-limited/unavailable messages below already tell the user the
    problem is momentary and to try again - this makes that actually true
    for a few seconds before giving up and surfacing it, instead of failing
    the whole task on the very first hiccup. Non-transient errors (bad
    credentials, no credit, a bad request) are raised immediately on the
    first attempt since retrying them can never help.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await make_call()
        except Exception as exc:  # noqa: BLE001
            if attempt >= max_attempts or not is_transient_llm_error(exc):
                raise
            delay = base_delay_seconds * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                "Transient LLM error on attempt %s/%s, retrying in %.1fs: %r",
                attempt,
                max_attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)

NOT_CONFIGURED_MESSAGES = [
    "Hmm, nobody's ever actually plugged me in. I don't have a working brain hooked up yet - an "
    "administrator needs to finish setting that up before I can think, chat, or plan anything.",
    "I showed up to work and realized I was never actually given a brain. An administrator needs "
    "to finish my setup before I can do anything useful here.",
]

OUT_OF_CREDIT_MESSAGES = [
    "Dude, I'm tired — I need energy. My AI brain's run out of juice, and until an administrator "
    "tops up the account, I've got nothing left to think with.",
    "Running on empty over here. I'm out of fuel for my AI brain, and I can't think on fumes — an "
    "administrator needs to add more credit before I can get back to work.",
    "I hit empty. Literally can't form a thought until an administrator refills my AI budget. "
    "Feed me credit, then I'm good to go.",
]

BAD_CREDENTIALS_MESSAGES = [
    "I tried to clock in and got turned away at the door — my own credentials got rejected. An "
    "administrator needs to sort that out before I can think again.",
    "Something's wrong with my badge — the AI service won't let me in with it. An administrator "
    "needs to fix my setup before I'm back online.",
]

RATE_LIMITED_MESSAGES = [
    "Whoa, slow down — I'm getting hit with requests faster than I can think. Give me a moment and "
    "try again.",
    "I'm a little overwhelmed right now, too many requests at once. Try again in a bit.",
]

# Deliberately does NOT say "give me a moment" or "try again shortly" like
# the burst-limit messages above - a daily cap resets hours away, not
# seconds away, so promising a quick fix here would just be untrue.
DAILY_QUOTA_EXHAUSTED_MESSAGES = [
    "I've used up all the thinking I'm allowed for today and I'm tapped out until it resets later. "
    "An administrator can raise today's limit, or it'll free up on its own after the reset.",
    "I'm out of today's allowance for thinking, not just temporarily overloaded - this won't clear "
    "up on retry. An administrator needs to either raise the daily limit or wait it out with you.",
]

UNAVAILABLE_MESSAGES = [
    "My brain's service is having a bad day and isn't answering right now. Give it a little while "
    "and try again.",
    "The lights are flickering upstairs — my AI service is temporarily down. Try again shortly.",
]

GENERIC_API_MESSAGES = [
    "My AI brain choked on that one and I'm not totally sure why. Mind trying again?",
    "Something went sideways trying to think that through. Give it another shot.",
]

GENERIC_MESSAGES = [
    "I zoned out for a second there and something went wrong while I was thinking. Try again in a "
    "moment?",
    "My train of thought derailed mid-way through that one. Try again in a bit.",
]

# Kept for anything that constructs this constant by name elsewhere; a single
# (first) variant, since some callers want one fixed string rather than a
# random pick (e.g. tests asserting on content).
NOT_CONFIGURED_MESSAGE = NOT_CONFIGURED_MESSAGES[0]


def humanize_llm_error(exc: Exception) -> str:
    """Return a short, plain-language, in-character, user-facing message for
    `exc`. Always logs the real technical detail first so it is never
    silently lost, just kept out of the user-facing surface."""
    logger.warning("LLM request failed: %r", exc)

    if isinstance(exc, APIStatusError):
        if exc.status_code == 402:
            return random.choice(OUT_OF_CREDIT_MESSAGES)
        if exc.status_code == 401:
            return random.choice(BAD_CREDENTIALS_MESSAGES)
        if exc.status_code == 429:
            if _is_exhausted_daily_quota(exc):
                return random.choice(DAILY_QUOTA_EXHAUSTED_MESSAGES)
            return random.choice(RATE_LIMITED_MESSAGES)
        if exc.status_code and exc.status_code >= 500:
            return random.choice(UNAVAILABLE_MESSAGES)
        return random.choice(GENERIC_API_MESSAGES)

    return random.choice(GENERIC_MESSAGES)
