from app.audit.integrity import canonical_json, list_audit, record_audit, verify_chain


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
