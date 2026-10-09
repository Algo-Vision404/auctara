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

import logging
import random

from openai import APIStatusError

logger = logging.getLogger("agentauth.llm_errors")

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
            return random.choice(RATE_LIMITED_MESSAGES)
        if exc.status_code and exc.status_code >= 500:
            return random.choice(UNAVAILABLE_MESSAGES)
        return random.choice(GENERIC_API_MESSAGES)

    return random.choice(GENERIC_MESSAGES)
