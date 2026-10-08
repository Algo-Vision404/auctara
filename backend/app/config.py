"""Central application configuration loaded from environment variables.

No secret or policy value is ever hard-coded for production behaviour;
everything here is overridable via the environment / .env file.
"""
from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # OpenRouter (OpenAI compatible)
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Database
    database_url: str = "sqlite:///./agentauth.db"

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
    # (simplest — what this sandbox and `docker-compose up` use).
    # False: run `python worker.py` as a separate process/Render worker
    # service instead, and leave this off on the web service so recurring
    # tasks aren't triggered twice.
    run_scheduler_inprocess: bool = True

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
        return "./agentauth.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
