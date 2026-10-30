"""Thin repository layer over SQLite. No ORM, deliberately simple per spec."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.database.database import get_connection, immediate_transaction


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()} if row else None


# ---------------------------------------------------------------- agents --
def create_agent(name: str, purpose: str, directive: str) -> dict:
    conn = get_connection()
    agent_id = new_id("agent")
    conn.execute(
        "INSERT INTO agents (id, name, purpose, directive, status) VALUES (?,?,?,?, 'ACTIVE')",
        (agent_id, name, purpose, directive),
    )
    return get_agent(agent_id)


def get_agent(agent_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    return row_to_dict(row)


def list_agents() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM agents ORDER BY created_at DESC").fetchall()
    return [row_to_dict(r) for r in rows]


def update_agent_status(agent_id: str, status: str) -> Optional[dict]:
    conn = get_connection()
    conn.execute("UPDATE agents SET status=? WHERE id=?", (status, agent_id))
    return get_agent(agent_id)


def delete_agent(agent_id: str) -> None:
    """Permanently remove an agent. `PRAGMA foreign_keys = ON` (set on every
    connection, see database.py) plus `ON DELETE CASCADE` on policies,
    tasks, transactions, scheduled_tasks, and budget_ledger means this one
    statement also removes every row that belongs to this agent in those
    tables. activity_events and audit_records deliberately have NO foreign
    key back to agents (plain text columns) and are therefore never touched
    by this cascade: the permanent, hash-chained audit trail must survive an
    agent being deleted, even though the live entity and its transactions
    are gone from the normal product surface. Callers are expected to have
    already cancelled any in-flight work for this agent (see
    orchestrator.delete_agent) before calling this.
    """
    conn = get_connection()
    conn.execute("DELETE FROM agents WHERE id=?", (agent_id,))


# -------------------------------------------------------------- policies --
def create_policy(agent_id: str, policy: dict) -> dict:
    conn = get_connection()
    conn.execute("UPDATE policies SET active=0 WHERE agent_id=?", (agent_id,))
    policy_id = new_id("policy")
    conn.execute(
        """INSERT INTO policies
        (id, agent_id, max_transaction_amount, approval_threshold, daily_limit, monthly_limit,
         velocity_max_transactions, velocity_window_minutes, price_variance_tolerance,
         blocked_categories, allowed_categories, categories, active)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
        (
            policy_id,
            agent_id,
            policy["max_transaction_amount"],
            policy["approval_threshold"],
            policy["daily_limit"],
            policy["monthly_limit"],
            policy.get("velocity", {}).get("max_transactions", 5),
            policy.get("velocity", {}).get("window_minutes", 60),
            policy.get("price_variance_tolerance", 0.05),
            json.dumps(policy.get("blocked_categories", [])),
            json.dumps(policy.get("allowed_categories", [])),
            json.dumps(policy.get("categories", [])),
        ),
    )
    return get_active_policy(agent_id)


def get_active_policy(agent_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM policies WHERE agent_id=? AND active=1 ORDER BY created_at DESC LIMIT 1",
        (agent_id,),
    ).fetchone()
    d = row_to_dict(row)
    if d:
        d["blocked_categories"] = json.loads(d["blocked_categories"])
        d["allowed_categories"] = json.loads(d["allowed_categories"])
        d["categories"] = json.loads(d.get("categories") or "[]")
    return d


# ------------------------------------------------------------------ tasks --
def create_task(agent_id: str, prompt: str, max_amount: float | None,
                 frontend_origin: str | None = None, scheduled_task_id: str | None = None,
                 paypal_negative_test: str | None = None) -> dict:
    conn = get_connection()
    task_id = new_id("task")
    conn.execute(
        "INSERT INTO tasks (id, agent_id, prompt, max_amount, status, frontend_origin, scheduled_task_id, "
        "paypal_negative_test) VALUES (?,?,?,?, 'CREATED', ?, ?, ?)",
        (task_id, agent_id, prompt, max_amount, frontend_origin, scheduled_task_id, paypal_negative_test),
    )
    return get_task(task_id)


def get_task(task_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return row_to_dict(row)


def list_tasks(agent_id: str | None = None) -> list[dict]:
    conn = get_connection()
    if agent_id:
        rows = conn.execute("SELECT * FROM tasks WHERE agent_id=? ORDER BY created_at DESC", (agent_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    return [row_to_dict(r) for r in rows]


def update_task_status(task_id: str, status: str, error: str | None = None) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE tasks SET status=?, error=?, updated_at=? WHERE id=?",
        (status, error, now_iso(), task_id),
    )


# ------------------------------------------------------------ transactions --
def create_transaction(task_id: str, agent_id: str) -> dict:
    conn = get_connection()
    tx_id = new_id("tx")
    conn.execute(
        "INSERT INTO transactions (id, task_id, agent_id, state) VALUES (?,?,?, 'CREATED')",
        (tx_id, task_id, agent_id),
    )
    return get_transaction(tx_id)


def get_transaction(tx_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT t.*, a.name AS agent_name, k.prompt AS task_prompt, k.paypal_negative_test AS paypal_negative_test "
        "FROM transactions t "
        "JOIN agents a ON a.id = t.agent_id "
        "LEFT JOIN tasks k ON k.id = t.task_id "
        "WHERE t.id=?",
        (tx_id,),
    ).fetchone()
    return row_to_dict(row)


def get_transaction_for_task(task_id: str) -> Optional[dict]:
    """The one transaction a task owns. run_task creates exactly one
    transaction per task up front and every later step (including pausing
    for clarification and resuming) keeps reusing that same row, so "most
    recent for this task_id" is always the right (and only) one."""
    conn = get_connection()
    row = conn.execute(
        "SELECT t.*, a.name AS agent_name, k.prompt AS task_prompt, k.paypal_negative_test AS paypal_negative_test "
        "FROM transactions t "
        "JOIN agents a ON a.id = t.agent_id "
        "LEFT JOIN tasks k ON k.id = t.task_id "
        "WHERE t.task_id=? ORDER BY t.created_at DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    return row_to_dict(row)


def list_transactions(agent_id: str | None = None) -> list[dict]:
    conn = get_connection()
    base = (
        "SELECT t.*, a.name AS agent_name, k.prompt AS task_prompt, k.paypal_negative_test AS paypal_negative_test "
        "FROM transactions t "
        "JOIN agents a ON a.id = t.agent_id "
        "LEFT JOIN tasks k ON k.id = t.task_id"
    )
    if agent_id:
        rows = conn.execute(base + " WHERE t.agent_id=? ORDER BY t.created_at DESC", (agent_id,)).fetchall()
    else:
        rows = conn.execute(base + " ORDER BY t.created_at DESC").fetchall()
    return [row_to_dict(r) for r in rows]


def update_transaction(tx_id: str, **fields: Any) -> dict:
    conn = get_connection()
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [tx_id]
    conn.execute(f"UPDATE transactions SET {cols} WHERE id=?", values)
    return get_transaction(tx_id)


def atomic_transition(tx_id: str, current: str, target: str, **fields: Any) -> Optional[dict]:
    """Atomically move a transaction from `current` to `target`, succeeding
    only if the row is still actually in `current` at the moment of the
    write. The orchestrator's own abstract state-machine check
    (`transition()`) validates that current->target is a legal edge at
    all, but that alone does not stop two concurrent callers who both read
    the same starting state from both believing they are the one making
    the move - exactly the shape of bug already fixed for the scheduler
    and PayPal-continue races. Wrapping the read-check-and-write in one
    conditional UPDATE inside BEGIN IMMEDIATE means at most one of them
    can ever match the WHERE clause, so at most one proceeds to whatever
    real side effect (creating a PayPal order, etc.) comes next.

    Returns the updated row on success, or None if the row was not in
    `current` right now (lost a race to a concurrent transition, or the
    caller's belief about the current state was simply stale/wrong).
    """
    fields = dict(fields)
    fields["state"] = target
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [tx_id, current]
    with immediate_transaction() as conn:
        cur = conn.execute(
            f"UPDATE transactions SET {cols} WHERE id=? AND state=?",
            values,
        )
        if cur.rowcount != 1:
            return None
    return get_transaction(tx_id)


def claim_paypal_continue(tx_id: str) -> bool:
    """Atomically claim the right to call PayPal's authorize/capture APIs
    for this transaction's `continue_after_paypal_approval` step. Returns
    True exactly once per transaction (whichever call gets there first);
    every later call - a duplicate/retried request to the same endpoint
    from a page refresh while `?paypal=return` is still in the URL, the
    user hitting back/forward, or PayPal redirecting twice - gets False
    and must not touch PayPal again for this transaction.

    Uses the same BEGIN IMMEDIATE pattern as budget reservations and the
    scheduler's due-schedule claim, for the same reason: two concurrent
    callers can never both believe they're the one entitled to authorize/
    capture this specific PayPal order.
    """
    with immediate_transaction() as conn:
        cur = conn.execute(
            "UPDATE transactions SET paypal_continue_claimed_at=?, updated_at=? "
            "WHERE id=? AND state='VERIFYING' AND paypal_continue_claimed_at IS NULL",
            (now_iso(), now_iso(), tx_id),
        )
        return cur.rowcount == 1


# ------------------------------------------------------------- budget math --
def get_spent_since(agent_id: str, since_iso: str) -> float:
    """Sum of committed budget (RESERVE + CAPTURE_ADJUST, minus RELEASE)
    for every transaction *created* since a timestamp - this is what feeds
    the actual daily/monthly limit check in app.guardrails.policies, not
    just the dashboard's display figures, so getting the date boundary
    right here is a real spending-control correctness issue, not a
    cosmetic one.

    Filters on the owning transaction's own created_at (joining through
    transaction_id), deliberately NOT each ledger row's own created_at,
    the same convention count_transactions_since already uses below. A
    transaction's lifecycle can span real wall-clock gaps - held in
    VERIFYING for a while, reconciled later by the scheduler's stale sweep,
    etc. - so its RESERVE and its eventual RELEASE/CAPTURE_ADJUST legs can
    land on different calendar days (or, for the monthly cutoff, different
    calendar months) even though they both belong to one transaction that
    was decided on one particular day. Filtering by each leg's own
    timestamp would then only pick up, say, a transaction's -$12 RELEASE
    posted after midnight while missing the +$12 RESERVE posted before it
    - making "spent today" go negative for a transaction that was never
    actually part of today at all, and in turn making that agent's
    computed daily_remaining exceed its real daily_limit. Attributing the
    whole transaction's net ledger effect to the single day it was created
    keeps every transaction counted exactly once, in exactly one day's (or
    month's) total, no matter when its individual ledger legs happen to
    post.
    """
    conn = get_connection()
    row = conn.execute(
        """SELECT COALESCE(SUM(budget_ledger.amount), 0) as total
           FROM budget_ledger
           JOIN transactions ON transactions.id = budget_ledger.transaction_id
           WHERE budget_ledger.agent_id=? AND transactions.created_at >= ?""",
        (agent_id, since_iso),
    ).fetchone()
    return float(row["total"])


def count_transactions_since(agent_id: str, since_iso: str) -> int:
    conn = get_connection()
    row = conn.execute(
        """SELECT COUNT(*) as c FROM transactions
           WHERE agent_id=? AND created_at >= ? AND state NOT IN ('BLOCKED','FAILED','CREATED')""",
        (agent_id, since_iso),
    ).fetchone()
    return int(row["c"])


def reserve_budget(agent_id: str, transaction_id: str, amount: float) -> None:
    """Atomically record a budget reservation. Must be called inside immediate_transaction."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO budget_ledger (id, agent_id, transaction_id, amount, entry_type) VALUES (?,?,?,?, 'RESERVE')",
        (new_id("ledger"), agent_id, transaction_id, amount),
    )


def adjust_budget(agent_id: str, transaction_id: str, delta: float, entry_type: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO budget_ledger (id, agent_id, transaction_id, amount, entry_type) VALUES (?,?,?,?,?)",
        (new_id("ledger"), agent_id, transaction_id, delta, entry_type),
    )


def release_budget(agent_id: str, transaction_id: str, amount: float) -> None:
    adjust_budget(agent_id, transaction_id, -amount, "RELEASE")


def start_of_day_iso() -> str:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def start_of_month_iso() -> str:
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def window_start_iso(minutes: int) -> str:
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return start.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# -------------------------------------------------------------- activity --
def add_activity(agent_id: str | None, task_id: str | None, transaction_id: str | None,
                  event_type: str, message: str, payload: dict | None = None) -> dict:
    conn = get_connection()
    aid = new_id("act")
    conn.execute(
        """INSERT INTO activity_events (id, task_id, transaction_id, agent_id, event_type, message, payload)
           VALUES (?,?,?,?,?,?,?)""",
        (aid, task_id, transaction_id, agent_id, event_type, message, json.dumps(payload or {})),
    )
    row = conn.execute("SELECT * FROM activity_events WHERE id=?", (aid,)).fetchone()
    d = row_to_dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def list_activity(task_id: str | None = None, limit: int = 100, order: str = "desc") -> list[dict]:
    """Real activity events, optionally scoped to one task.

    `order="desc"` (the default) is most-recent-first and respects `limit`;
    this is what powers a live feed that prepends new events as they arrive.
    `order="asc"` returns the full, unlimited chronological history for a
    task, oldest first, for a top-to-bottom timeline reading.
    """
    conn = get_connection()
    direction = "ASC" if order == "asc" else "DESC"
    if task_id:
        if order == "asc":
            rows = conn.execute(
                f"SELECT * FROM activity_events WHERE task_id=? ORDER BY created_at {direction}", (task_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM activity_events WHERE task_id=? ORDER BY created_at {direction} LIMIT ?",
                (task_id, limit),
            ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM activity_events ORDER BY created_at {direction} LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


# ----------------------------------------------------------- scheduled tasks --
RECURRENCE_STEPS = {
    "ONCE": None,
    "DAILY": timedelta(days=1),
    "WEEKLY": timedelta(weeks=1),
    "MONTHLY": timedelta(days=30),
}


def create_scheduled_task(agent_id: str, prompt: str, max_amount: float | None,
                            recurrence: str, start_at: str) -> dict:
    conn = get_connection()
    sched_id = new_id("sched")
    conn.execute(
        "INSERT INTO scheduled_tasks (id, agent_id, prompt, max_amount, recurrence, start_at, next_run_at, status) "
        "VALUES (?,?,?,?,?,?,?, 'ACTIVE')",
        (sched_id, agent_id, prompt, max_amount, recurrence, start_at, start_at),
    )
    return get_scheduled_task(sched_id)


def get_scheduled_task(sched_id: str) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM scheduled_tasks WHERE id=?", (sched_id,)).fetchone()
    return row_to_dict(row)


def list_scheduled_tasks(agent_id: str | None = None) -> list[dict]:
    conn = get_connection()
    if agent_id:
        rows = conn.execute(
            "SELECT * FROM scheduled_tasks WHERE agent_id=? ORDER BY next_run_at ASC", (agent_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM scheduled_tasks ORDER BY next_run_at ASC").fetchall()
    return [row_to_dict(r) for r in rows]


def list_stale_verifying_transactions(older_than_iso: str) -> list[dict]:
    """Transactions still sitting in VERIFYING (a PayPal order was created,
    the buyer was sent off to approve it) that haven't moved since before
    `older_than_iso`. Used by the scheduler's reconciliation sweep to find
    ones the normal redirect-driven flow may never resolve on its own - the
    buyer closed the tab, lost their connection, or the redirect back
    simply never arrived. paypal_order_id IS NOT NULL is always true for a
    real VERIFYING row (the order is created in the same step that sets the
    state), but is checked anyway so a malformed/partial row can never be
    handed to code that assumes one exists.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE state='VERIFYING' AND paypal_order_id IS NOT NULL "
        "AND updated_at <= ? ORDER BY updated_at ASC",
        (older_than_iso,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def get_last_activity_at(task_id: str) -> Optional[str]:
    """The created_at of the most recent activity_events row for this task,
    or None if it has no activity logged at all (defensive only - every
    real task gets at least TASK_CREATED/AGENT_STARTED the instant it's
    created, so this should never actually happen, but a caller deciding
    whether to fail a transaction as abandoned must never crash on a
    partial/malformed row instead of just falling back to something else).
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(created_at) AS last_at FROM activity_events WHERE task_id=?",
        (task_id,),
    ).fetchone()
    return row["last_at"] if row else None


def list_stale_active_transactions(states: list[str], older_than_iso: str) -> list[dict]:
    """Transactions in any of `states` whose own updated_at is older than
    `older_than_iso` - a coarse first-pass filter only. updated_at on a
    transaction row only moves when it changes *state*, not on every step
    a research loop takes while it stays in the same state (those land in
    activity_events instead), so this alone cannot tell a truly stalled
    transaction from one still actively working just inside the same
    state. The caller (orchestrator.reconcile_orphaned_transaction) makes
    the real per-transaction call by also checking get_last_activity_at.
    """
    conn = get_connection()
    placeholders = ",".join("?" for _ in states)
    rows = conn.execute(
        f"SELECT * FROM transactions WHERE state IN ({placeholders}) AND updated_at <= ? "
        "ORDER BY updated_at ASC",
        (*states, older_than_iso),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def list_due_scheduled_tasks(now_iso: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE status='ACTIVE' AND next_run_at <= ? ORDER BY next_run_at ASC",
        (now_iso,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def claim_due_scheduled_task(sched_id: str, now_iso: str, next_run_at: Optional[str], new_status: str) -> bool:
    """Atomically re-verify a schedule is still due and advance it past
    "due" in one indivisible step. Returns True if this call won the claim
    (the row has been advanced), False if it was no longer due by the time
    this ran (already claimed by a concurrent scheduler instance, or
    paused/cancelled in between) - the caller must not fire a task in
    that case.

    Closes a real race: the scheduler is explicitly designed to run either
    in-process or as a separate `worker.py` process (see scheduler.py's
    module docstring) - if both ever run at once (a misconfiguration, or a
    worker service horizontally scaled to more than one instance), two
    pollers could both see the same schedule as due via the plain SELECT
    in list_due_scheduled_tasks before either advances next_run_at, and
    both fire a real task through the real PayPal pipeline for the same
    occurrence - double-charging the renewal this schedule represents.
    This mirrors the same BEGIN IMMEDIATE protection budget reservations
    already get, for the same reason: two concurrent callers can never
    both believe they're the one entitled to fire this occurrence.
    """
    with immediate_transaction() as conn:
        row = conn.execute(
            "SELECT 1 FROM scheduled_tasks WHERE id=? AND status='ACTIVE' AND next_run_at<=?",
            (sched_id, now_iso),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE scheduled_tasks SET next_run_at=?, last_run_at=?, status=?, updated_at=? WHERE id=?",
            (next_run_at or now_iso, now_iso, new_status, now_iso, sched_id),
        )
    return True


def update_scheduled_task(sched_id: str, **fields: Any) -> dict:
    conn = get_connection()
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [sched_id]
    conn.execute(f"UPDATE scheduled_tasks SET {cols} WHERE id=?", values)
    return get_scheduled_task(sched_id)


# A schedule's status has no equivalent of the transaction state machine
# (see app/state_machine.py) guarding it - update_scheduled_task above will
# happily blind-write any status onto any row, for any caller, which is
# fine for the system's own internal, trusted writes (the scheduler
# advancing/cancelling a row it just evaluated, an agent retirement
# force-cancelling one). PATCH /schedules/{id} is the one caller that
# forwards a human-supplied status straight through, and COMPLETED/
# CANCELLED are meant to be true terminal states - the product's own UI
# never offers a way back out of either (no action buttons render for a
# COMPLETED schedule; CANCELLED has no "undo"). Without a real guard here,
# reactivating a COMPLETED ONCE-schedule back to ACTIVE left its
# next_run_at exactly where claim_due_scheduled_task set it when the
# schedule fired - in the past - so the very next scheduler tick would see
# it as due all over again and fire a second real task (and therefore a
# second real PayPal purchase attempt) for an occurrence that had already
# completed.
SCHEDULE_STATUS_EDGES: dict[str, set[str]] = {
    "ACTIVE": {"PAUSED", "CANCELLED"},
    "PAUSED": {"ACTIVE", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def transition_schedule_status(sched_id: str, target_status: str) -> Optional[dict]:
    """Atomically move a scheduled task to `target_status`, succeeding only
    if its current status still has that edge available. Returns the
    updated row, or None if the row no longer exists, the move isn't a
    legal edge from its current status (e.g. target is already-COMPLETED
    or already-CANCELLED), or a concurrent caller already moved it out of
    the status this call still believed it was in.

    Uses the same BEGIN IMMEDIATE compare-and-swap pattern as
    atomic_transition/claim_due_scheduled_task, for the same reason: two
    concurrent PATCH calls (a double-click, two open tabs) must never both
    believe they are the one making this move.
    """
    with immediate_transaction() as conn:
        row = conn.execute("SELECT status FROM scheduled_tasks WHERE id=?", (sched_id,)).fetchone()
        if row is None:
            return None
        current = row["status"]
        if target_status not in SCHEDULE_STATUS_EDGES.get(current, set()):
            return None
        conn.execute(
            "UPDATE scheduled_tasks SET status=?, updated_at=? WHERE id=? AND status=?",
            (target_status, now_iso(), sched_id, current),
        )
        cur = conn.execute("SELECT changes()").fetchone()
        if cur[0] != 1:
            return None
    return get_scheduled_task(sched_id)


def delete_scheduled_task(sched_id: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (sched_id,))


def list_runs_for_schedule(sched_id: str) -> list[dict]:
    """Every real task this schedule has ever actually fired (scheduler.py
    stamps `scheduled_task_id` on each one it spawns), joined with that
    task's transaction outcome where one exists yet. This is what lets the
    Bryntum timeline plot a schedule's genuine execution history - real
    past firings with their real outcomes - rather than only ever showing a
    single synthetic recurring-rule pattern with no record of what actually
    happened each time it fired.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT
               k.id AS task_id,
               k.created_at AS fired_at,
               k.status AS task_status,
               t.id AS transaction_id,
               t.state AS transaction_state,
               t.decision AS decision,
               t.merchant AS merchant,
               t.amount AS amount,
               t.currency AS currency
           FROM tasks k
           LEFT JOIN transactions t ON t.task_id = k.id
           WHERE k.scheduled_task_id = ?
           ORDER BY k.created_at ASC""",
        (sched_id,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def compute_next_run(current_next_run_iso: str, recurrence: str) -> Optional[str]:
    """Advance a schedule's next_run_at by one recurrence step. Returns None
    for ONCE (the schedule has nothing left to do after it fires)."""
    step = RECURRENCE_STEPS.get(recurrence)
    if step is None:
        return None
    current = datetime.strptime(current_next_run_iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    nxt = current + step
    # If the schedule fell behind (e.g. server was down), skip forward to the
    # next future occurrence instead of rapid-firing a backlog of runs.
    while nxt <= now:
        nxt += step
    return nxt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
