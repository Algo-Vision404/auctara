"""Tests for the Agent Operations Schedule (app/scheduler.py).

run_task (the real agent -> policy -> PayPal pipeline) is monkeypatched to a
no-op here so these tests isolate the scheduler's own responsibilities:
detecting due schedules, spawning a real persisted task for each one,
advancing next_run_at by the right recurrence step, and handling inactive
agents safely. The actual pipeline is already covered end-to-end by the
other test modules and by live verification.
"""
import asyncio

import pytest

from app.database import models
from app import scheduler


def _make_agent():
    agent = models.create_agent("Procurement Agent", "Buy office supplies", "Buy cheap supplies")
    models.create_policy(agent["id"], {
        "max_transaction_amount": 200, "approval_threshold": 150,
        "daily_limit": 500, "monthly_limit": 3000,
        "velocity": {"max_transactions": 5, "window_minutes": 60},
        "blocked_categories": [], "allowed_categories": [],
    })
    return agent


@pytest.mark.asyncio
async def test_due_schedule_triggers_a_real_task(monkeypatch):
    triggered_task_ids = []

    async def fake_run_task(task_id):
        triggered_task_ids.append(task_id)

    monkeypatch.setattr(scheduler, "run_task", fake_run_task)

    agent = _make_agent()
    past = "2020-01-01T00:00:00.000000Z"
    sched = models.create_scheduled_task(agent["id"], "Buy printer paper", 50, "DAILY", past)

    n = await scheduler.run_due_schedules()
    await asyncio.sleep(0)  # let the fire-and-forget asyncio.create_task(run_task(...)) actually run
    assert n == 1
    assert len(triggered_task_ids) == 1

    updated = models.get_scheduled_task(sched["id"])
    assert updated["status"] == "ACTIVE"
    assert updated["last_task_id"] == triggered_task_ids[0]
    assert updated["last_run_at"] is not None
    # DAILY recurrence must skip forward past "now", not just +1 day from 2020.
    assert updated["next_run_at"] > models.now_iso()

    task = models.get_task(triggered_task_ids[0])
    assert task["scheduled_task_id"] == sched["id"]
    assert task["prompt"] == "Buy printer paper"


@pytest.mark.asyncio
async def test_once_schedule_completes_after_firing(monkeypatch):
    monkeypatch.setattr(scheduler, "run_task", lambda task_id: asyncio.sleep(0))

    agent = _make_agent()
    sched = models.create_scheduled_task(agent["id"], "One-off purchase", 20, "ONCE", "2020-01-01T00:00:00.000000Z")

    n = await scheduler.run_due_schedules()
    assert n == 1

    updated = models.get_scheduled_task(sched["id"])
    assert updated["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_future_schedule_is_not_triggered(monkeypatch):
    monkeypatch.setattr(scheduler, "run_task", lambda task_id: asyncio.sleep(0))

    agent = _make_agent()
    future = "2099-01-01T00:00:00.000000Z"
    models.create_scheduled_task(agent["id"], "Future purchase", 20, "ONCE", future)

    n = await scheduler.run_due_schedules()
    assert n == 0


@pytest.mark.asyncio
async def test_inactive_agent_schedule_is_skipped_not_fabricated(monkeypatch):
    calls = []
    monkeypatch.setattr(scheduler, "run_task", lambda task_id: calls.append(task_id) or asyncio.sleep(0))

    agent = _make_agent()
    models.update_task_status  # sanity import check only
    from app.database.database import get_connection
    get_connection().execute("UPDATE agents SET status='PAUSED' WHERE id=?", (agent["id"],))

    sched = models.create_scheduled_task(agent["id"], "Should not run", 20, "ONCE", "2020-01-01T00:00:00.000000Z")

    n = await scheduler.run_due_schedules()
    assert n == 0
    assert calls == []

    updated = models.get_scheduled_task(sched["id"])
    assert updated["status"] == "CANCELLED"


def test_concurrent_claims_on_the_same_due_schedule_never_both_win(monkeypatch):
    """The scheduler module is explicitly designed to run either in-process
    or as a separate `worker.py` process (see scheduler.py's module
    docstring). If both ever ran at once - a misconfiguration, or a worker
    service horizontally scaled past one instance - two ticks racing on
    the same due schedule used to be able to both see it as due (the plain
    SELECT in list_due_scheduled_tasks) before either advanced
    next_run_at, and both would go on to fire a real task through the real
    PayPal pipeline for the same occurrence - double-charging the renewal
    it represents.

    claim_due_scheduled_task is the primitive that's supposed to make that
    impossible (BEGIN IMMEDIATE around a re-check-then-advance). asyncio
    can't actually exercise that guarantee here, because every step from
    the read to the write is synchronous with no `await` in between - the
    same "accidentally atomic" situation the audit chain had. This test
    uses real OS threads instead (each gets its own SQLite connection, as
    in test_audit.py's equivalent test) to prove the protection is real at
    the database level, not just a property of this particular test
    happening not to interleave.
    """
    import threading

    agent = _make_agent()
    past = "2020-01-01T00:00:00.000000Z"
    sched = models.create_scheduled_task(agent["id"], "Renew subscription", 50, "DAILY", past)
    now_iso = models.now_iso()
    nxt = models.compute_next_run(sched["next_run_at"], sched["recurrence"])

    results: list[bool] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def worker():
        try:
            won = models.claim_due_scheduled_task(sched["id"], now_iso, nxt, "ACTIVE")
            with lock:
                results.append(won)
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"claim_due_scheduled_task raised under concurrency: {errors}"
    assert results.count(True) == 1, f"expected exactly one winner, got {results}"
    assert results.count(False) == 7

    updated = models.get_scheduled_task(sched["id"])
    assert updated["status"] == "ACTIVE"
    assert updated["next_run_at"] == nxt


def test_compute_next_run_skips_backlog_to_the_future():
    old = "2020-01-01T00:00:00.000000Z"
    nxt = models.compute_next_run(old, "DAILY")
    assert nxt is not None
    assert nxt > models.now_iso()


def test_compute_next_run_once_returns_none():
    assert models.compute_next_run("2020-01-01T00:00:00.000000Z", "ONCE") is None


@pytest.mark.asyncio
async def test_schedule_runs_reflects_real_firing_history(monkeypatch):
    """list_runs_for_schedule (and GET /schedules/{id}/runs) is what lets the
    Bryntum timeline plot a schedule's actual past executions, not just a
    synthetic repeating pattern - so it needs to return every task this
    schedule really spawned, each joined with whatever transaction outcome
    exists for it so far (None before the pipeline has created one yet)."""
    monkeypatch.setattr(scheduler, "run_task", lambda task_id: asyncio.sleep(0))

    agent = _make_agent()
    sched = models.create_scheduled_task(
        agent["id"], "Buy printer paper", 50, "DAILY", "2020-01-01T00:00:00.000000Z"
    )

    n = await scheduler.run_due_schedules()
    assert n == 1

    runs = models.list_runs_for_schedule(sched["id"])
    assert len(runs) == 1
    assert runs[0]["task_status"] == "CREATED"
    # The fake run_task never advances the pipeline, so no transaction has
    # been created for this task yet - must be reported as None, never
    # fabricated, so the frontend can render "pending" rather than a fake
    # outcome.
    assert runs[0]["transaction_id"] is None
    assert runs[0]["fired_at"] is not None

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        resp = client.get(f"/schedules/{sched['id']}/runs")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["task_id"] == runs[0]["task_id"]

        missing = client.get("/schedules/sched_doesnotexist/runs")
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_reactivating_a_completed_once_schedule_is_rejected(monkeypatch):
    """A ONCE schedule's next_run_at is left exactly where it was the
    moment it fired - in the past (see claim_due_scheduled_task). Before
    transition_schedule_status existed, update_scheduled_task would
    blindly write status='ACTIVE' back onto a COMPLETED row with no check
    at all, and the very next scheduler tick would see that past
    next_run_at as due all over again - firing a second real task (and in
    production, a second real PayPal purchase attempt) for an occurrence
    that had already completed. COMPLETED must be a true dead end.
    """
    monkeypatch.setattr(scheduler, "run_task", lambda task_id: asyncio.sleep(0))

    agent = _make_agent()
    sched = models.create_scheduled_task(
        agent["id"], "One-off purchase", 20, "ONCE", "2020-01-01T00:00:00.000000Z"
    )
    n = await scheduler.run_due_schedules()
    assert n == 1
    assert models.get_scheduled_task(sched["id"])["status"] == "COMPLETED"

    result = models.transition_schedule_status(sched["id"], "ACTIVE")
    assert result is None
    assert models.get_scheduled_task(sched["id"])["status"] == "COMPLETED"

    # The real-world consequence this guards against: without the fix, the
    # schedule would now be due again and a second scheduler tick would
    # fire it a second time.
    n2 = await scheduler.run_due_schedules()
    assert n2 == 0
    assert models.get_scheduled_task(sched["id"])["status"] == "COMPLETED"


def test_cancelled_schedule_cannot_be_reactivated():
    agent = _make_agent()
    sched = models.create_scheduled_task(agent["id"], "Renewal", 20, "MONTHLY", "2099-01-01T00:00:00.000000Z")
    assert models.transition_schedule_status(sched["id"], "CANCELLED")["status"] == "CANCELLED"
    assert models.transition_schedule_status(sched["id"], "ACTIVE") is None
    assert models.get_scheduled_task(sched["id"])["status"] == "CANCELLED"


def test_legitimate_pause_and_resume_still_work():
    agent = _make_agent()
    sched = models.create_scheduled_task(agent["id"], "Renewal", 20, "WEEKLY", "2099-01-01T00:00:00.000000Z")
    paused = models.transition_schedule_status(sched["id"], "PAUSED")
    assert paused["status"] == "PAUSED"
    resumed = models.transition_schedule_status(sched["id"], "ACTIVE")
    assert resumed["status"] == "ACTIVE"


def test_patch_schedules_endpoint_rejects_reactivating_a_completed_schedule():
    from fastapi.testclient import TestClient
    from app.main import app

    agent = _make_agent()
    sched = models.create_scheduled_task(agent["id"], "One-off", 20, "ONCE", "2020-01-01T00:00:00.000000Z")
    # Simulate it having already fired and completed, same as a real tick would.
    models.update_scheduled_task(sched["id"], status="COMPLETED")

    with TestClient(app) as client:
        resp = client.patch(f"/schedules/{sched['id']}", json={"status": "ACTIVE"})
        assert resp.status_code == 400
        assert models.get_scheduled_task(sched["id"])["status"] == "COMPLETED"

        # The legitimate PAUSED -> ACTIVE path through the real endpoint still works.
        sched2 = models.create_scheduled_task(agent["id"], "Recurring", 20, "DAILY", "2099-01-01T00:00:00.000000Z")
        models.update_scheduled_task(sched2["id"], status="PAUSED")
        resp2 = client.patch(f"/schedules/{sched2['id']}", json={"status": "ACTIVE"})
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "ACTIVE"
