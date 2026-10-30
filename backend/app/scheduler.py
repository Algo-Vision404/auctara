"""Background execution of recurring agent commerce (the Bryntum-driven
Agent Operations Schedule), plus reconciliation of PayPal checkouts that
never came back on their own.

On every poll tick this:
  1. Finds scheduled tasks whose `next_run_at` has arrived, spawns a
     genuine `run_task()` through the normal agent -> policy -> PayPal
     pipeline (no shortcuts, no simulated outcomes), and advances the
     schedule's `next_run_at` by its recurrence.
  2. Finds transactions stuck in VERIFYING (a PayPal order was created,
     the buyer was sent off to approve it) past
     Settings.paypal_verification_timeout_minutes, and resolves each one
     - checking PayPal for what actually happened rather than assuming
     the worst - instead of leaving them (and the budget they reserved)
     stuck forever if the buyer's redirect back never arrives.
  3. Finds transactions orphaned by a server crash/restart/deploy while a
     background research/propose/policy coroutine was the only thing that
     could ever move them forward (see
     Settings.orphaned_task_timeout_minutes and
     orchestrator.ORPHANABLE_STATES), and fails each one cleanly - a
     dead process's in-memory work can never be resumed, so the only
     honest outcome is an explicit failure instead of leaving it stuck
     forever with no explanation.

Runs either in-process (default, convenient for local/dev and this sandbox,
controlled by Settings.run_scheduler_inprocess) or as a standalone process
via worker.py for a real separate Render worker service in production.
"""
from __future__ import annotations

import asyncio
import logging

from app.agent.orchestrator import (
    emit,
    reconcile_orphaned_transactions,
    reconcile_stale_verifying_transactions,
    run_task,
)
from app.database import models

logger = logging.getLogger("auctara.scheduler")

POLL_INTERVAL_SECONDS = 15



async def run_due_schedules() -> int:
    """Check for due scheduled tasks and trigger real execution for each.
    Returns the number of tasks triggered (useful for tests/logging)."""
    now_iso = models.now_iso()
    due = models.list_due_scheduled_tasks(now_iso)
    triggered = 0
    for sched in due:
        agent = models.get_agent(sched["agent_id"])
        if not agent or agent["status"] != "ACTIVE":
            # Agent no longer exists/active. Push the schedule forward so it
            # doesn't spin hot, but never fabricate a run for a dead agent.
            nxt = models.compute_next_run(sched["next_run_at"], sched["recurrence"])
            if nxt:
                models.update_scheduled_task(sched["id"], next_run_at=nxt)
            else:
                models.update_scheduled_task(sched["id"], status="CANCELLED")
            continue

        # Claim this occurrence atomically BEFORE firing anything: advances
        # next_run_at past "due" inside its own BEGIN IMMEDIATE, re-checking
        # the row is still due at the moment of the claim. If a concurrent
        # scheduler instance (see claim_due_scheduled_task's docstring) got
        # there first, this returns False and we skip it rather than firing
        # a second real task - and therefore a second real PayPal order -
        # for the same occurrence.
        nxt = models.compute_next_run(sched["next_run_at"], sched["recurrence"])
        won_claim = models.claim_due_scheduled_task(
            sched["id"], now_iso, nxt, "ACTIVE" if nxt else "COMPLETED"
        )
        if not won_claim:
            continue

        task = models.create_task(
            sched["agent_id"], sched["prompt"], sched.get("max_amount"),
            scheduled_task_id=sched["id"],
        )
        await emit(
            "SCHEDULED_TASK_TRIGGERED",
            f"Scheduled task fired for {agent['name']}: \"{sched['prompt'][:80]}\"",
            task_id=task["id"], agent_id=agent["id"],
            payload={"scheduled_task_id": sched["id"], "recurrence": sched["recurrence"]},
        )
        # The claim above already advanced next_run_at/status; this just
        # attaches the real task id once it exists.
        models.update_scheduled_task(sched["id"], last_task_id=task["id"])

        asyncio.create_task(run_task(task["id"]))
        triggered += 1
    return triggered


async def scheduler_loop(stop_event: "asyncio.Event | None" = None) -> None:
    """Infinite polling loop. Pass a stop_event for graceful shutdown/tests."""
    logger.info("Scheduler loop started (poll every %ss).", POLL_INTERVAL_SECONDS)
    while not (stop_event and stop_event.is_set()):
        try:
            n = await run_due_schedules()
            if n:
                logger.info("Triggered %d scheduled task(s).", n)
        except Exception:  # noqa: BLE001
            logger.exception("Scheduler tick failed")
        try:
            reconciled = await reconcile_stale_verifying_transactions()
            if reconciled:
                logger.info("Reconciled %d stale VERIFYING transaction(s).", reconciled)
        except Exception:  # noqa: BLE001
            logger.exception("Stale-VERIFYING reconciliation tick failed")
        try:
            orphaned = await reconcile_orphaned_transactions()
            if orphaned:
                logger.info("Reconciled %d orphaned transaction(s) stuck with no activity.", orphaned)
        except Exception:  # noqa: BLE001
            logger.exception("Orphaned-transaction reconciliation tick failed")
        try:
            if stop_event:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_SECONDS)
            else:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
