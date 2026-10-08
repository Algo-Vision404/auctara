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
