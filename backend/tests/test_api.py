import time

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "paypal_configured" in data


def test_create_and_list_agents():
    with TestClient(app) as client:
        payload = {
            "name": "Research Agent",
            "purpose": "Manage SaaS subscriptions",
            "directive": "Find and buy project management software",
            "policy": {
                "max_transaction_amount": 150,
                "approval_threshold": 100,
                "daily_limit": 300,
                "monthly_limit": 2000,
                "velocity": {"max_transactions": 5, "window_minutes": 60},
                "blocked_categories": ["gambling", "crypto"],
                "allowed_categories": [],
            },
        }
        resp = client.post("/agents", json=payload)
        assert resp.status_code == 200
        agent = resp.json()
        assert agent["policy"]["approval_threshold"] == 100

        resp = client.get("/agents")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        resp = client.get(f"/agents/{agent['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Research Agent"


def test_policy_rejects_invalid_threshold():
    with TestClient(app) as client:
        payload = {
            "name": "Bad Agent", "purpose": "x", "directive": "x",
            "policy": {
                "max_transaction_amount": 50, "approval_threshold": 100,
                "daily_limit": 300, "monthly_limit": 2000,
            },
        }
        resp = client.post("/agents", json=payload)
        assert resp.status_code == 400


def test_policy_evaluate_dry_run():
    with TestClient(app) as client:
        payload = {
            "name": "Procurement Agent", "purpose": "x", "directive": "x",
            "policy": {
                "max_transaction_amount": 150, "approval_threshold": 100,
                "daily_limit": 300, "monthly_limit": 2000,
                "blocked_categories": ["gambling"], "allowed_categories": [],
            },
        }
        agent = client.post("/agents", json=payload).json()

        allow_resp = client.post("/policies/evaluate", json={
            "agent_id": agent["id"], "amount": 63.99, "category": "software",
        })
        assert allow_resp.json()["decision"] == "ALLOW"

        approval_resp = client.post("/policies/evaluate", json={
            "agent_id": agent["id"], "amount": 149, "category": "software",
        })
        assert approval_resp.json()["decision"] == "APPROVAL_REQUIRED"

        block_resp = client.post("/policies/evaluate", json={
            "agent_id": agent["id"], "amount": 420, "category": "software",
        })
        assert block_resp.json()["decision"] == "BLOCK"

        blocked_category_resp = client.post("/policies/evaluate", json={
            "agent_id": agent["id"], "amount": 10, "category": "gambling",
        })
        assert blocked_category_resp.json()["decision"] == "BLOCK"


def test_task_without_openrouter_key_fails_visibly_not_silently():
    """With no AI key configured, the task must fail with a real, visible
    error — never pretend to succeed with fabricated data."""
    with TestClient(app) as client:
        payload = {
            "name": "Unconfigured Agent", "purpose": "x", "directive": "x",
            "policy": {
                "max_transaction_amount": 150, "approval_threshold": 100,
                "daily_limit": 300, "monthly_limit": 2000,
            },
        }
        agent = client.post("/agents", json=payload).json()

        task = client.post("/tasks", json={"agent_id": agent["id"], "prompt": "Buy software"}).json()

        status = None
        for _ in range(20):
            time.sleep(0.25)
            t = client.get(f"/tasks/{task['id']}").json()
            status = t["status"]
            if status == "FAILED":
                assert "OpenRouter" in (t["error"] or "")
                break
        assert status == "FAILED"


def test_dashboard_summary_and_audit_endpoints():
    with TestClient(app) as client:
        resp = client.get("/dashboard/summary")
        assert resp.status_code == 200
        assert "active_agents" in resp.json()

        resp = client.get("/audit/verify")
        assert resp.status_code == 200
        assert resp.json()["valid"] is True
