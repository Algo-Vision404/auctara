"""Tamper-evident audit trail.

Every audit record is canonically serialised and chained with HMAC-SHA256,
so any record contains a hash of (its own payload + the previous record's
hash). This lets an auditor verify the whole chain has not been altered.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Optional

from app.config import get_settings
from app.database.database import get_connection, immediate_transaction
from app.database.models import new_id, now_iso, row_to_dict


GENESIS_HASH = "0" * 64


def canonical_json(data: dict) -> str:
    """Deterministic JSON serialisation: sorted keys, no extraneous whitespace."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, canonical_payload: str) -> str:
    secret = get_settings().audit_hmac_secret.encode("utf-8")
    message = f"{prev_hash}:{canonical_payload}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def _last_hash() -> str:
    conn = get_connection()
    row = conn.execute("SELECT hash FROM audit_records ORDER BY seq DESC LIMIT 1").fetchone()
    return row["hash"] if row else GENESIS_HASH


def record_audit(
    event_type: str,
    payload: dict,
    transaction_id: Optional[str] = None,
    task_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> dict:
    # Reading the previous record's hash/seq and inserting the next one is a
    # classic read-then-write: two records appended "at the same time" could
    # otherwise both read the same prev_hash/seq and both insert as if they
    # were the chain's new tail, breaking the one-parent-per-record
    # invariant verify_chain() depends on - which would make a perfectly
    # legitimate, untampered chain fail verification, undermining the one
    # thing this module exists to guarantee. This app's single asyncio
    # event loop happens to make record_audit() calls atomic today (no
    # `await` ever appears between the read and the write), but that is an
    # accident of the current single-worker deployment, not a guarantee -
    # the exact same reasoning already governs every budget-ledger write
    # (see immediate_transaction's docstring), so the audit chain, which
    # makes a much louder promise ("tamper-evident"), gets the same real,
    # SQLite-level protection rather than relying on it.
    with immediate_transaction() as conn:
        prev_hash = _last_hash()
        body = {
            "event_type": event_type,
            "transaction_id": transaction_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "payload": payload,
        }
        canonical = canonical_json(body)
        record_hash = compute_hash(prev_hash, canonical)
        record_id = new_id("audit")
        row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 as next_seq FROM audit_records").fetchone()
        seq = row["next_seq"]
        conn.execute(
            """INSERT INTO audit_records (id, seq, transaction_id, task_id, agent_id, event_type, payload, prev_hash, hash)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (record_id, seq, transaction_id, task_id, agent_id, event_type,
             json.dumps(payload), prev_hash, record_hash),
        )
    return get_audit_record(record_id)


def get_audit_record(record_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM audit_records WHERE id=?", (record_id,)).fetchone()
    d = row_to_dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def list_audit(transaction_id: Optional[str] = None, limit: int = 200) -> list[dict]:
    conn = get_connection()
    if transaction_id:
        rows = conn.execute(
            "SELECT * FROM audit_records WHERE transaction_id=? ORDER BY seq ASC", (transaction_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM audit_records ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def verify_chain() -> dict:
    """Recompute the hash chain from genesis and confirm integrity."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM audit_records ORDER BY seq ASC").fetchall()
    prev_hash = GENESIS_HASH
    for r in rows:
        d = row_to_dict(r)
        payload = json.loads(d["payload"])
        body = {
            "event_type": d["event_type"],
            "transaction_id": d["transaction_id"],
            "task_id": d["task_id"],
            "agent_id": d["agent_id"],
            "payload": payload,
        }
        canonical = canonical_json(body)
        expected_hash = compute_hash(prev_hash, canonical)
        if expected_hash != d["hash"] or d["prev_hash"] != prev_hash:
            return {"valid": False, "broken_at_seq": d["seq"], "record_id": d["id"]}
        prev_hash = d["hash"]
    return {"valid": True, "records_verified": len(rows)}
