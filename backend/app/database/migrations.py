"""Schema creation / migration. Idempotent — safe to call on every boot."""
from __future__ import annotations

from app.database.database import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT NOT NULL,
    directive TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    max_transaction_amount REAL NOT NULL,
    approval_threshold REAL NOT NULL,
    daily_limit REAL NOT NULL,
    monthly_limit REAL NOT NULL,
    velocity_max_transactions INTEGER NOT NULL DEFAULT 5,
    velocity_window_minutes INTEGER NOT NULL DEFAULT 60,
    price_variance_tolerance REAL NOT NULL DEFAULT 0.05,
    blocked_categories TEXT NOT NULL DEFAULT '[]',
    allowed_categories TEXT NOT NULL DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    max_amount REAL,
    status TEXT NOT NULL DEFAULT 'CREATED',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY,
    task_id TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    merchant TEXT,
    amount REAL,
    currency TEXT DEFAULT 'USD',
    category TEXT,
    reason TEXT,
    source_url TEXT,
    state TEXT NOT NULL DEFAULT 'CREATED',
    decision TEXT,
    decision_reason TEXT,
    authorized_amount REAL,
    expected_amount REAL,
    actual_amount REAL,
    remaining_daily_budget REAL,
    remaining_monthly_budget REAL,
    paypal_order_id TEXT,
    paypal_authorization_id TEXT,
    paypal_capture_id TEXT,
    paypal_status TEXT,
    paypal_approve_url TEXT,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    max_amount REAL,
    recurrence TEXT NOT NULL DEFAULT 'ONCE', -- ONCE, DAILY, WEEKLY, MONTHLY
    start_at TEXT NOT NULL,
    next_run_at TEXT NOT NULL,
    last_run_at TEXT,
    last_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE, PAUSED, CANCELLED
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS budget_ledger (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    transaction_id TEXT REFERENCES transactions(id) ON DELETE CASCADE,
    amount REAL NOT NULL,
    entry_type TEXT NOT NULL, -- RESERVE, CAPTURE_ADJUST, RELEASE
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS activity_events (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    transaction_id TEXT,
    agent_id TEXT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS audit_records (
    id TEXT PRIMARY KEY,
    seq INTEGER,
    transaction_id TEXT,
    task_id TEXT,
    agent_id TEXT,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_tx_agent ON transactions(agent_id);
CREATE INDEX IF NOT EXISTS idx_tx_task ON transactions(task_id);
CREATE INDEX IF NOT EXISTS idx_ledger_agent ON budget_ledger(agent_id);
CREATE INDEX IF NOT EXISTS idx_activity_task ON activity_events(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_seq ON audit_records(seq);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run ON scheduled_tasks(status, next_run_at);
"""


def run_migrations() -> None:
    conn = get_connection()
    conn.executescript(SCHEMA)
    _ensure_column(conn, "transactions", "paypal_approve_url", "TEXT")
    _ensure_column(conn, "tasks", "frontend_origin", "TEXT")
    _ensure_column(conn, "transactions", "image_url", "TEXT")
    _ensure_column(conn, "transactions", "retailer", "TEXT")
    _ensure_column(conn, "transactions", "channel3_product_id", "TEXT")
    _ensure_column(conn, "tasks", "scheduled_task_id", "TEXT")


def _ensure_column(conn, table: str, column: str, coltype: str) -> None:
    cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
