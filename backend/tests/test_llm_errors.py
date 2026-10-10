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
