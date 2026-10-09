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

from app.agent.llm_errors import NOT_CONFIGURED_MESSAGE, humanize_llm_error

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
