"""SQLite connection management.

Uses WAL mode for concurrency, foreign keys enforced, and BEGIN IMMEDIATE
for any write that touches financial/budget state so concurrent requests
cannot double-spend the same budget.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

from app.config import get_settings

_local = threading.local()


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(settings.sqlite_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 15000;")
    return conn


def get_connection() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = _connect()
    return _local.conn


@contextmanager
def immediate_transaction():
    """Context manager that opens a BEGIN IMMEDIATE transaction.

    Use for any operation that reserves / debits budget so two concurrent
    requests can never both believe they have remaining capacity.
    """
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE;")
    try:
        yield conn
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise


@contextmanager
def plain_cursor():
    conn = get_connection()
    try:
        yield conn
    finally:
        pass
