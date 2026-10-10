"""The message shown to a user when an LLM call fails must be plain,
in-character language - never "OpenRouter", an env var name, a dashboard
URL, or a raw HTTP status/SDK exception string. See app/agent/llm_errors.py.
Messages are randomized (a small pool of variants per failure type) for
personality/variety, so these tests check for the presence of the right
*theme*, not one exact fixed string.
"""
from __future__ import annotations

import httpx
import pytest
from openai import APIStatusError

from app.agent.llm_errors import (
    DAILY_QUOTA_EXHAUSTED_MESSAGES,
    NOT_CONFIGURED_MESSAGE,
    call_llm_with_retry,
    humanize_llm_error,
    is_transient_llm_error,
)

TECHNICAL_TERMS = ["OpenRouter", "OPENROUTER", ".env", "openrouter.ai", "HTTP "]


def _status_error(status_code: int, body: dict | None = None) -> APIStatusError:
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(status_code, request=request, json=body or {"error": {"message": "boom"}})
    return APIStatusError("boom", response=response, body=body or {"error": {"message": "boom"}})


def _daily_quota_exhausted_error(*, wrapped: bool = False) -> APIStatusError:
    # Shaped like OpenRouter's real response when a free model's 50
    # requests/day cap has hit zero (seen live in this project's own
    # account): metadata.limit_source ends in "daily", and the message
    # itself says "per-day". The openai SDK's own `exc.body`, as actually
    # observed live against the real API, holds this *unwrapped* (no outer
    # "error" key) - `wrapped=True` recreates the raw-HTTP-response shape
    # instead, since both have been seen and must both be handled.
    inner = {
        "message": (
            "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free "
            "model requests per day"
        ),
        "code": 429,
        "metadata": {
            "headers": {"X-RateLimit-Limit": "50", "X-RateLimit-Remaining": "0"},
            "limit_source": "openrouter_free_tier_daily",
        },
    }
    body = {"error": inner} if wrapped else inner
    return _status_error(429, body)


@pytest.mark.parametrize("status_code", [402, 401, 429, 500, 503, 418])
def test_api_status_errors_are_plain_language(status_code):
    for _ in range(10):  # messages are randomized; sample several draws
        message = humanize_llm_error(_status_error(status_code))
        for term in TECHNICAL_TERMS:
            assert term not in message, f"status {status_code} leaked technical term {term!r}: {message}"
        assert message  # never empty


def test_insufficient_credit_message_is_actionable_but_not_technical():
    seen = set()
    theme_words = ["credit", "juice", "energy", "fuel", "budget"]
    for _ in range(20):
        message = humanize_llm_error(_status_error(402))
        seen.add(message)
        assert "administrator" in message
        assert any(w in message.lower() for w in theme_words), message
    # Confirms the randomized pool is actually being exercised, not just
    # always returning the same single string.
    assert len(seen) > 1


def test_rate_limit_message_invites_retry_without_mentioning_administrator():
    message = humanize_llm_error(_status_error(429))
    assert "try again" in message.lower()


def test_generic_exception_is_plain_language():
    message = humanize_llm_error(RuntimeError("some raw internal detail"))
    for term in TECHNICAL_TERMS:
        assert term not in message
    assert "some raw internal detail" not in message


def test_not_configured_message_has_no_technical_terms():
    for term in TECHNICAL_TERMS:
        assert term not in NOT_CONFIGURED_MESSAGE
    assert "administrator" in NOT_CONFIGURED_MESSAGE


@pytest.mark.parametrize("status_code", [429, 500, 502, 503])
def test_rate_limit_and_server_errors_are_transient(status_code):
    assert is_transient_llm_error(_status_error(status_code)) is True


@pytest.mark.parametrize("status_code", [400, 401, 402, 403, 404])
def test_client_errors_are_not_transient(status_code):
    assert is_transient_llm_error(_status_error(status_code)) is False


def test_generic_exceptions_are_not_transient():
    # A plain RuntimeError (e.g. a bug, or something unrelated to the LLM
    # call itself) should never be retried - only recognized
    # rate-limit/connection/5xx failures are worth a second try.
    assert is_transient_llm_error(RuntimeError("boom")) is False


async def test_call_with_retry_recovers_from_a_transient_rate_limit():
    attempts = []

    async def flaky_call():
        attempts.append(1)
        if len(attempts) < 3:
            raise _status_error(429)
        return "ok"

    result = await call_llm_with_retry(flaky_call, base_delay_seconds=0.01)
    assert result == "ok"
    assert len(attempts) == 3


async def test_call_with_retry_gives_up_after_max_attempts():
    attempts = []

    async def always_rate_limited():
        attempts.append(1)
        raise _status_error(429)

    with pytest.raises(APIStatusError):
        await call_llm_with_retry(always_rate_limited, max_attempts=3, base_delay_seconds=0.01)
    assert len(attempts) == 3


async def test_call_with_retry_does_not_retry_bad_credentials():
    attempts = []

    async def bad_credentials():
        attempts.append(1)
        raise _status_error(401)

    with pytest.raises(APIStatusError):
        await call_llm_with_retry(bad_credentials, max_attempts=5, base_delay_seconds=0.01)
    # Non-transient: must fail on the very first attempt, not waste time
    # retrying something that will never succeed.
    assert len(attempts) == 1


def test_a_plain_burst_rate_limit_is_transient():
    # A 429 with no daily-cap metadata at all (the generic/default case) is
    # still treated as a short-lived burst worth retrying.
    assert is_transient_llm_error(_status_error(429)) is True


def test_an_exhausted_daily_quota_is_not_transient():
    # A 429 that is specifically OpenRouter's free-model *daily* cap won't
    # clear up within a few seconds of retrying - it only resets hours
    # later - so it must not be treated as worth a short retry. This is the
    # shape actually seen from the real openai SDK against the real API:
    # exc.body holds the inner error object directly, with no outer
    # "error" key.
    assert is_transient_llm_error(_daily_quota_exhausted_error()) is False


def test_an_exhausted_daily_quota_is_not_transient_in_the_wrapped_body_shape_too():
    # Same check, but against the alternate "error" key wrapped shape, in
    # case a different SDK version or code path ever produces that instead.
    assert is_transient_llm_error(_daily_quota_exhausted_error(wrapped=True)) is False


async def test_call_with_retry_does_not_retry_an_exhausted_daily_quota():
    attempts = []

    async def daily_quota_exhausted():
        attempts.append(1)
        raise _daily_quota_exhausted_error()

    with pytest.raises(APIStatusError):
        await call_llm_with_retry(daily_quota_exhausted, max_attempts=5, base_delay_seconds=0.01)
    assert len(attempts) == 1


def test_daily_quota_message_is_honest_about_the_wait_not_momentary():
    message = humanize_llm_error(_daily_quota_exhausted_error())
    assert message in DAILY_QUOTA_EXHAUSTED_MESSAGES
    # Must not promise a quick fix like the brief-burst message does - a
    # daily cap resets hours away, not seconds away.
    assert "moment" not in message.lower()
    assert "shortly" not in message.lower()
    for term in TECHNICAL_TERMS:
        assert term not in message
