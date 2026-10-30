import os
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / "tests" / "test_auctara.db"


@pytest.fixture(autouse=True, scope="function")
def clean_db(tmp_path, monkeypatch):
    db_path = tmp_path / "auctara_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("AUDIT_HMAC_SECRET", "test-secret")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    # Tests drive scheduling logic directly (test_scheduler.py) rather than
    # via the real background poll loop, so keep it off during API/app tests
    # for determinism and speed.
    monkeypatch.setenv("RUN_SCHEDULER_INPROCESS", "false")

    from app.config import get_settings
    get_settings.cache_clear()

    from app.database import database as db_module
    db_module._local.conn = None

    from app.database.migrations import run_migrations
    run_migrations()

    yield

    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _scope_guard_defaults_to_in_scope(monkeypatch):
    """The independent scope guard (app.agent.scope_guard.check_scope) makes
    its own real Groq call, separate from whatever a test already
    stubbed out for the main research loop. GROQ_API_KEY is "" for
    every test (see clean_db above), so without this, every test that
    doesn't specifically care about the scope guard would see it fail
    closed (ok=False) on every single transaction, silently turning every
    would-be ALLOW into APPROVAL_REQUIRED for a reason that has nothing to
    do with what that test is actually exercising - and tests that record/
    assert on the exact number of LLM calls made would also see one extra
    call that was never theirs to account for.

    Default every test to "the independent scope check said yes" so the
    pre-existing ALLOW/APPROVAL_REQUIRED/BLOCK behavior is unaffected by
    this guard's existence. A test that specifically wants to exercise the
    scope guard's own disagreement or fail-closed behavior can override
    this after the fact with its own monkeypatch.setattr(orchestrator,
    "check_scope", ...) call - autouse fixtures apply before the test body
    runs, so a later call in the test itself simply takes precedence.
    """
    import app.agent.orchestrator as orchestrator
    from app.agent.scope_guard import ScopeVerdict

    async def _always_in_scope(*args, **kwargs):
        return ScopeVerdict(ok=True, in_scope=True, reason="test default: in scope")

    monkeypatch.setattr(orchestrator, "check_scope", _always_in_scope)


@pytest.fixture(autouse=True)
def _specificity_check_defaults_to_specific_enough(monkeypatch):
    """_check_task_specificity (the pre-flight "does this task name a
    product/use case AND a budget" gate run once at the very start of a
    brand-new task) makes its own independent real Groq call too,
    same situation as check_scope above: GROQ_API_KEY is "" for every
    test, so without this, every test driving a real task through the
    actual POST /tasks -> run_task path (not just ones calling
    _run_research_loop directly) would see this gate fail open/closed in
    whatever way an unconfigured client happens to raise, adding an
    unaccounted-for pause/behavior that has nothing to do with what that
    test is actually exercising.

    Default every test to "specific enough, proceed" so pre-existing
    ALLOW/APPROVAL_REQUIRED/BLOCK behavior is unaffected by this gate's
    existence. A test that specifically wants to exercise the gate itself
    overrides this after the fact with its own monkeypatch.setattr(
    orchestrator, "_check_task_specificity", ...) call, same override
    pattern as the scope guard fixture above.
    """
    import app.agent.orchestrator as orchestrator

    async def _always_specific_enough(*args, **kwargs):
        return None

    monkeypatch.setattr(orchestrator, "_check_task_specificity", _always_specific_enough)
