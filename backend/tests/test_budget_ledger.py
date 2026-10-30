from app.database import models
from app.database.database import immediate_transaction


def setup_agent():
    agent = models.create_agent("Test Agent", "Testing", "Spend wisely")
    models.create_policy(agent["id"], {
        "max_transaction_amount": 150, "approval_threshold": 100,
        "daily_limit": 300, "monthly_limit": 2000,
        "velocity": {"max_transactions": 5, "window_minutes": 60},
        "blocked_categories": [], "allowed_categories": [],
    })
    return agent


def test_reserve_budget_accumulates():
    agent = setup_agent()
    tx1 = models.create_transaction(None, agent["id"])
    tx2 = models.create_transaction(None, agent["id"])

    with immediate_transaction():
        models.reserve_budget(agent["id"], tx1["id"], 50)
    with immediate_transaction():
        models.reserve_budget(agent["id"], tx2["id"], 30)

    spent = models.get_spent_since(agent["id"], models.start_of_day_iso())
    assert spent == 80


def test_release_budget_reduces_spent():
    agent = setup_agent()
    tx1 = models.create_transaction(None, agent["id"])
    with immediate_transaction():
        models.reserve_budget(agent["id"], tx1["id"], 50)
    models.release_budget(agent["id"], tx1["id"], 50)
    spent = models.get_spent_since(agent["id"], models.start_of_day_iso())
    assert spent == 0


def test_velocity_counter_ignores_blocked_and_created():
    agent = setup_agent()
    tx1 = models.create_transaction(None, agent["id"])
    models.update_transaction(tx1["id"], state="BLOCKED")
    tx2 = models.create_transaction(None, agent["id"])
    models.update_transaction(tx2["id"], state="COMPLETED")

    count = models.count_transactions_since(agent["id"], models.window_start_iso(60))
    assert count == 1


def test_spent_today_is_not_negative_when_a_transactions_release_crosses_midnight():
    """Reproduces a real bug: a transaction reserved late one day (e.g. an
    agent proposal right before midnight, or more commonly a transaction
    that sat in VERIFYING for a long time) whose RELEASE/CAPTURE_ADJUST leg
    does not post until the *next* calendar day. get_spent_since used to
    sum ledger rows by each row's own created_at, so "spent today" would
    only pick up that later-posted -$X RELEASE while missing the +$X
    RESERVE that actually belongs to yesterday - making "spent today" go
    negative for a transaction that was never part of today at all, and in
    turn making the agent's computed daily_remaining exceed its real
    daily_limit. The fix attributes a transaction's whole net ledger effect
    to the single day the transaction itself was created.
    """
    agent = setup_agent()
    tx = models.create_transaction(None, agent["id"])
    conn = models.get_connection()

    yesterday = "2026-01-01T23:59:00.000000Z"
    today = "2026-01-02T00:05:00.000000Z"
    conn.execute("UPDATE transactions SET created_at=? WHERE id=?", (yesterday, tx["id"]))

    with immediate_transaction():
        models.reserve_budget(agent["id"], tx["id"], 12.0)
    conn.execute(
        "UPDATE budget_ledger SET created_at=? WHERE transaction_id=? AND entry_type='RESERVE'",
        (yesterday, tx["id"]),
    )

    # The release itself posts "today" - after the transaction (and its
    # reservation) actually happened, as a stale-VERIFYING timeout would.
    models.release_budget(agent["id"], tx["id"], 12.0)
    conn.execute(
        "UPDATE budget_ledger SET created_at=? WHERE transaction_id=? AND entry_type='RELEASE'",
        (today, tx["id"]),
    )

    spent_today = models.get_spent_since(agent["id"], today)
    assert spent_today == 0, f"a transaction entirely from yesterday polluted today's spend: {spent_today}"
