"""Tests for app/api/routes/tasks.py - specifically _browser_origin's trust
boundary, which decides what PayPal's return_url/cancel_url point at for a
task's eventual checkout (see execute_payment in app/agent/orchestrator.py).

The Origin/Referer headers this reads are 100% attacker-controlled - no
browser or CORS involved, a plain POST with a custom header is enough -
so anything accepted here that isn't already trusted for CORS is an open
redirect sitting right after a real PayPal payment approval.
"""
from fastapi.testclient import TestClient

from app.database import models
from app.main import app


def _make_agent():
    agent = models.create_agent("Procurement Agent", "Buy office supplies", "Buy cheap supplies")
    models.create_policy(agent["id"], {
        "max_transaction_amount": 200, "approval_threshold": 150,
        "daily_limit": 500, "monthly_limit": 3000,
        "velocity": {"max_transactions": 5, "window_minutes": 60},
        "blocked_categories": [], "allowed_categories": [],
    })
    return agent


def test_forged_origin_header_is_not_trusted_as_the_paypal_return_url_host():
    agent = _make_agent()
    with TestClient(app) as client:
        resp = client.post(
            "/tasks",
            json={"agent_id": agent["id"], "prompt": "buy pens"},
            headers={"Origin": "https://evil.example"},
        )
        assert resp.status_code == 200
        task = resp.json()
        # Must NOT be echoed back - this would become the literal PayPal
        # return_url/cancel_url host at checkout time otherwise.
        assert task["frontend_origin"] != "https://evil.example"
        assert task["frontend_origin"] is None


def test_forged_referer_header_is_also_not_trusted():
    agent = _make_agent()
    with TestClient(app) as client:
        resp = client.post(
            "/tasks",
            json={"agent_id": agent["id"], "prompt": "buy pens"},
            headers={"Referer": "https://evil.example/some/page"},
        )
        assert resp.status_code == 200
        task = resp.json()
        assert task["frontend_origin"] is None


def test_legitimate_localhost_origin_is_still_trusted_and_recorded():
    agent = _make_agent()
    with TestClient(app) as client:
        resp = client.post(
            "/tasks",
            json={"agent_id": agent["id"], "prompt": "buy pens"},
            headers={"Origin": "http://localhost:3000"},
        )
        assert resp.status_code == 200
        task = resp.json()
        assert task["frontend_origin"] == "http://localhost:3000"


def test_legitimate_e2b_preview_origin_is_still_trusted_and_recorded():
    agent = _make_agent()
    with TestClient(app) as client:
        resp = client.post(
            "/tasks",
            json={"agent_id": agent["id"], "prompt": "buy pens"},
            headers={"Origin": "https://3000-sandboxid123.e2b.app"},
        )
        assert resp.status_code == 200
        task = resp.json()
        assert task["frontend_origin"] == "https://3000-sandboxid123.e2b.app"


def test_lookalike_e2b_suffix_origin_is_rejected():
    """A regex anchored only at the start (match, not fullmatch) would let
    this slip through as "starts with something that looks like an allowed
    e2b.app preview host". Confirms the fullmatch semantics hold."""
    agent = _make_agent()
    with TestClient(app) as client:
        resp = client.post(
            "/tasks",
            json={"agent_id": agent["id"], "prompt": "buy pens"},
            headers={"Origin": "https://3000-sandboxid123.e2b.app.evil.example"},
        )
        assert resp.status_code == 200
        task = resp.json()
        assert task["frontend_origin"] is None
