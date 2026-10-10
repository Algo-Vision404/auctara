import threading
import time

import app.audit.integrity as integrity
from app.audit.integrity import canonical_json, list_audit, record_audit, verify_chain
from app.database.database import get_connection


def test_canonical_json_sorted_keys():
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b
    assert a == '{"a":2,"b":1}'


def test_record_audit_creates_chained_hash():
    r1 = record_audit("TASK_CREATED", {"prompt": "buy software"})
    r2 = record_audit("POLICY_EVALUATED", {"decision": "ALLOW"})
    assert r2["prev_hash"] == r1["hash"]
    assert r1["hash"] != r2["hash"]


def test_verify_chain_valid():
    record_audit("TASK_CREATED", {"x": 1})
    record_audit("POLICY_EVALUATED", {"x": 2})
    record_audit("PAYMENT_CAPTURED", {"x": 3})
    result = verify_chain()
    assert result["valid"] is True
    assert result["records_verified"] == 3


def test_record_audit_survives_genuinely_concurrent_writers(monkeypatch):
    """record_audit does a read-then-write (previous hash, next seq) before
    inserting. On this app's single asyncio event loop that happens to be
    atomic in practice (no `await` ever appears mid-function), but that's
    an accident of the current single-worker deployment, not a guarantee -
    a multi-worker/multi-process deployment would use real OS threads or
    processes instead, where two inserts could genuinely read the same
    prev_hash/seq and both believe they're the chain's new tail.

    This test forces that exact window open (a small sleep between the
    read and the write, injected the same way a slow disk or a busier
    system could) and then hammers record_audit from real Python threads,
    each with its own SQLite connection (get_connection() is thread-
    local). It proves `immediate_transaction()`'s BEGIN IMMEDIATE is what
    actually serializes the chain at the database level - not just that
    this particular test happened not to interleave.
    """
    original_last_hash = integrity._last_hash

    def slow_last_hash():
        value = original_last_hash()
        time.sleep(0.01)
        return value

    monkeypatch.setattr(integrity, "_last_hash", slow_last_hash)

    threads_n, per_thread = 6, 3
    errors: list[Exception] = []

    def worker(i: int):
        try:
            for j in range(per_thread):
                record_audit(f"CONCURRENT_TEST_{i}", {"i": i, "j": j})
        except Exception as exc:  # pragma: no cover - surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, f"record_audit raised under concurrency: {errors}"

    conn = get_connection()
    rows = conn.execute("SELECT seq FROM audit_records ORDER BY seq ASC").fetchall()
    seqs = [r["seq"] for r in rows]
    expected_total = threads_n * per_thread
    # No duplicate or skipped seq numbers: exactly 1..N, each exactly once -
    # impossible if two threads ever both inserted believing they were next.
    assert seqs == list(range(1, expected_total + 1))

    result = verify_chain()
    assert result["valid"] is True
    assert result["records_verified"] == expected_total


def test_verify_chain_detects_tamper():
    import json
    from app.database.database import get_connection

    record_audit("TASK_CREATED", {"x": 1})
    rec = record_audit("POLICY_EVALUATED", {"x": 2})

    conn = get_connection()
    conn.execute("UPDATE audit_records SET payload=? WHERE id=?",
                 (json.dumps({"x": 999}), rec["id"]))

    result = verify_chain()
    assert result["valid"] is False


def test_list_audit_filters_by_transaction():
    record_audit("TASK_CREATED", {}, transaction_id="tx_1")
    record_audit("POLICY_EVALUATED", {}, transaction_id="tx_2")
    records = list_audit(transaction_id="tx_1")
    assert len(records) == 1
    assert records[0]["transaction_id"] == "tx_1"
