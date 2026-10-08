import os
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "tests" / "test_agentauth.db"


@pytest.fixture(autouse=True, scope="function")
def clean_db(tmp_path, monkeypatch):
    db_path = tmp_path / "agentauth_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AUDIT_HMAC_SECRET", "test-secret")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")

    from app.config import get_settings
    get_settings.cache_clear()

    from app.database import database as db_module
    db_module._local.conn = None

    from app.database.migrations import run_migrations
    run_migrations()

    yield

    get_settings.cache_clear()
