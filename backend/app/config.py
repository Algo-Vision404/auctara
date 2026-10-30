"""Central application configuration loaded from environment variables.

No secret or policy value is ever hard-coded for production behaviour;
everything here is overridable via the environment / .env file.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# The one place "which frontend origins does this backend actually trust"
# is defined, so CORS (app/main.py, which imports TRUSTED_ORIGIN_REGEX.pattern
# directly rather than keeping its own separate copy) and the PayPal
# return/cancel URL a task's browser-reported origin is allowed to influence
# (app/api/routes/tasks.py's _browser_origin) can never drift out of sync
# with each other.
#
# Two preview domain families are trusted, not just one: the raw sandbox
# host (https://{port}-{sandboxId}.e2b.app) AND the branded wrapper domain
# the hosting platform actually puts in front of it for end users
# (https://{slug}.arena.site) - a real user's browser is on the latter, not
# the former, so trusting only e2b.app silently broke the PayPal return
# redirect (and anything else keyed off the browser's real origin) for
# every real user, even though it worked in every direct-to-sandbox test.
#
# fullmatch, not match/search: an unanchored-at-the-end pattern would let
# something like "https://x.e2b.app.evil.example" slip through as a
# "contains an allowed substring" match.
TRUSTED_ORIGIN_REGEX = re.compile(r"https://.*\.(e2b\.app|arena\.site)")


def is_trusted_frontend_origin(origin: str | None) -> bool:
    if not origin:
        return False
    settings = get_settings()
    if origin in settings.trusted_frontend_origins:
        return True
    return bool(TRUSTED_ORIGIN_REGEX.fullmatch(origin))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


    # PayPal
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_environment: str = "sandbox"
    paypal_test_card_number: str = ""
    paypal_test_card_expiry: str = ""  # format YYYY-MM
    paypal_test_card_cvv: str = ""
    paypal_test_card_name: str = ""

    # Groq (OpenAI compatible)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Database
    database_url: str = "sqlite:///./auctara.db"

    # Audit
    audit_hmac_secret: str = "change-me-in-production"

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # Exchange rates
    exchange_rate_api_url: str = "https://open.er-api.com/v6/latest/USD"

    # Channel3 (real-time product discovery API for agentic commerce)
    channel3_api_key: str = ""
    channel3_base_url: str = "https://api.trychannel3.com"

    # Scheduler (Bryntum-driven Agent Operations Schedule).
    # True: the web process itself polls and fires due scheduled tasks
    # (simplest: what this sandbox and `docker-compose up` use).
    # False: run `python worker.py` as a separate process/Render worker
    # service instead, and leave this off on the web service so recurring
    # tasks aren't triggered twice.
    run_scheduler_inprocess: bool = True

    # How long a transaction may sit in VERIFYING (PayPal order created,
    # waiting on the buyer to approve/return) before the scheduler's own
    # reconciliation sweep (see app/scheduler.py) steps in and resolves it
    # one way or the other, instead of leaving it stuck forever if the
    # buyer closes the tab, loses their connection, or the redirect back
    # never arrives for any reason. Generous by default - this must never
    # fire while a real checkout could still legitimately be in progress.
    paypal_verification_timeout_minutes: int = 30

    # How long a transaction may sit with zero activity in any of the
    # states a background research/propose/policy/authorize coroutine must
    # be the one actively driving forward (see
    # orchestrator.ORPHANABLE_STATES) before the scheduler's reconciliation
    # sweep fails it cleanly. Unlike VERIFYING, nothing external (a human,
    # PayPal) can ever move one of these states forward on its own - if the
    # process actually running that coroutine dies (a crash, a deploy, a
    # sandbox reset), the transaction is stuck forever with no other way
    # out. Measured against the transaction's own *last activity event*,
    # not just time-since-it-entered-the-state, so a transaction that is
    # still genuinely working - just slowly, e.g. a sluggish free-tier LLM
    # or a web search falling back through several blocked providers - is
    # never failed out from under it; only true silence this long is ever
    # treated as abandoned.
    orphaned_task_timeout_minutes: int = 10

    @property
    def paypal_base_url(self) -> str:
        if self.paypal_environment.lower() == "live":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"

    @property
    def sqlite_path(self) -> str:
        url = self.database_url
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///"):]
        return "./auctara.db"

    @property
    def trusted_frontend_origins(self) -> set[str]:
        return {self.frontend_url, "http://localhost:3000", "http://127.0.0.1:3000"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
