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


# -------------------------------------------------------------- policies --
def create_policy(agent_id: str, policy: dict) -> dict:
    conn = get_connection()
    conn.execute("UPDATE policies SET active=0 WHERE agent_id=?", (agent_id,))
    policy_id = new_id("policy")
    conn.execute(
        """INSERT INTO policies
        (id, agent_id, max_transaction_amount, approval_threshold, daily_limit, monthly_limit,
         velocity_max_transactions, velocity_window_minutes, price_variance_tolerance,
         blocked_categories, allowed_categories, active)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
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
    return d


# ------------------------------------------------------------------ tasks --
def create_task(agent_id: str, prompt: str, max_amount: float | None,
                 frontend_origin: str | None = None, scheduled_task_id: str | None = None) -> dict:
    conn = get_connection()
    task_id = new_id("task")
    conn.execute(
        "INSERT INTO tasks (id, agent_id, prompt, max_amount, status, frontend_origin, scheduled_task_id) "
        "VALUES (?,?,?,?, 'CREATED', ?, ?)",
        (task_id, agent_id, prompt, max_amount, frontend_origin, scheduled_task_id),
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
        "SELECT t.*, a.name AS agent_name, k.prompt AS task_prompt "
        "FROM transactions t "
        "JOIN agents a ON a.id = t.agent_id "
        "LEFT JOIN tasks k ON k.id = t.task_id "
        "WHERE t.id=?",
        (tx_id,),
    ).fetchone()
    return row_to_dict(row)


def list_transactions(agent_id: str | None = None) -> list[dict]:
    conn = get_connection()
    base = (
        "SELECT t.*, a.name AS agent_name, k.prompt AS task_prompt "
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


# ------------------------------------------------------------- budget math --
def get_spent_since(agent_id: str, since_iso: str) -> float:
    """Sum of committed budget (RESERVE + CAPTURE_ADJUST, minus RELEASE) since a timestamp."""
    conn = get_connection()
    row = conn.execute(
        """SELECT COALESCE(SUM(amount), 0) as total FROM budget_ledger
           WHERE agent_id=? AND created_at >= ?""",
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


def list_due_scheduled_tasks(now_iso: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scheduled_tasks WHERE status='ACTIVE' AND next_run_at <= ? ORDER BY next_run_at ASC",
        (now_iso,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def update_scheduled_task(sched_id: str, **fields: Any) -> dict:
    conn = get_connection()
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [sched_id]
    conn.execute(f"UPDATE scheduled_tasks SET {cols} WHERE id=?", values)
    return get_scheduled_task(sched_id)


def delete_scheduled_task(sched_id: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (sched_id,))


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
