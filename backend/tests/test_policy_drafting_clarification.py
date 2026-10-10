"""Policy drafting used to be a single blind guess: natural-language
instructions in, a fully-formed JSON policy out, with no way for the model
to say "this is ambiguous, tell me more" before committing to assumed
numbers and scope. This exercises the fix: draft_policy_step can now pause
mid-conversation with a clarifying question (PolicyNeedsClarification),
exactly mirroring the shape of the main research loop's NEEDS_INPUT
pattern, and /agents/draft-policy surfaces that as
{"status": "needs_clarification", ...} instead of silently finishing.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.agent.policy_drafting as policy_drafting
from app.agent.policy_drafting import (
    MAX_POLICY_CLARIFICATION_ROUNDS,
    PolicyDraftError,
    PolicyNeedsClarification,
    draft_policy_step,
)
from app.main import app


def _fake_message(content: str):
    return SimpleNamespace(content=content)


class _SequentialCompletions:
    """Returns one canned reply per call, in order - mirrors the pattern
    already used by test_channel3_product_id_verification.py and
    test_clarification.py for the main research loop."""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self._idx = 0

    async def create(self, **kwargs):
        content = self._replies[min(self._idx, len(self._replies) - 1)]
        self._idx += 1
        return SimpleNamespace(choices=[SimpleNamespace(message=_fake_message(content))])


def _fake_client_sequence(replies: list[str]):
    client = SimpleNamespace(chat=SimpleNamespace(completions=_SequentialCompletions(replies)))
    return lambda: (client, SimpleNamespace(openrouter_model="fake-model"))


FULL_DRAFT = {
    "agent_name": "SaaS Agent",
    "agent_purpose": "Manage SaaS subscriptions",
    "max_transaction_amount": 150,
    "approval_threshold": 100,
    "daily_limit": 300,
    "monthly_limit": 2000,
    "velocity": {"max_transactions": 5, "window_minutes": 60},
    "price_variance_tolerance": 0.05,
    "blocked_categories": [],
    "allowed_categories": ["software", "subscriptions"],
    "assumptions": [],
}


async def test_ambiguous_instructions_pause_with_a_clarifying_question(monkeypatch):
    """A vague instruction gets a question back, not a silent guess."""
    question_reply = json.dumps({
        "type": "clarifying_question",
        "question": "Which specific SaaS tools should this agent manage?",
    })
    monkeypatch.setattr(policy_drafting, "_client_and_settings", _fake_client_sequence([question_reply]))

    try:
        await draft_policy_step([{"role": "user", "content": "Manage our SaaS subscriptions."}])
        assert False, "expected PolicyNeedsClarification"
    except PolicyNeedsClarification as clar:
        assert clar.question == "Which specific SaaS tools should this agent manage?"
        # The conversation handed back must include the assistant's own
        # question message, since the caller must round-trip it unchanged.
        assert clar.conversation[-1]["role"] == "assistant"
        assert "clarifying_question" in clar.conversation[-1]["content"]


async def test_answering_the_question_continues_to_a_real_draft(monkeypatch):
    """Once the human answers, the next call can produce the real draft -
    proving the conversation list is genuinely what carries continuity,
    not some hidden server-side state."""
    question_reply = json.dumps({
        "type": "clarifying_question",
        "question": "Which specific SaaS tools should this agent manage?",
    })
    draft_reply = json.dumps({"type": "policy_draft", "draft": FULL_DRAFT})
    monkeypatch.setattr(
        policy_drafting, "_client_and_settings",
        _fake_client_sequence([question_reply, draft_reply]),
    )

    conversation = [{"role": "user", "content": "Manage our SaaS subscriptions."}]
    try:
        await draft_policy_step(conversation)
        assert False, "expected PolicyNeedsClarification"
    except PolicyNeedsClarification as clar:
        conversation = [*clar.conversation, {"role": "user", "content": "Figma, Notion, and Slack."}]

    draft = await draft_policy_step(conversation)
    assert draft["allowed_categories"] == ["software", "subscriptions"]
    assert draft["assumptions"] == []


async def test_round_cap_forces_a_final_draft_instead_of_asking_forever(monkeypatch):
    """A model that keeps wanting to ask questions must be cut off after
    MAX_POLICY_CLARIFICATION_ROUNDS, not allowed to stall account setup
    indefinitely."""
    question_reply = json.dumps({"type": "clarifying_question", "question": "Which tools, exactly?"})
    final_reply = json.dumps({"type": "policy_draft", "draft": FULL_DRAFT})
    # One question reply per allowed round, then the forced final draft.
    replies = [question_reply] * MAX_POLICY_CLARIFICATION_ROUNDS + [final_reply]
    monkeypatch.setattr(policy_drafting, "_client_and_settings", _fake_client_sequence(replies))

    conversation = [{"role": "user", "content": "Manage our SaaS subscriptions."}]
    rounds = 0
    while True:
        try:
            draft = await draft_policy_step(conversation)
            break
        except PolicyNeedsClarification as clar:
            rounds += 1
            conversation = [*clar.conversation, {"role": "user", "content": "whatever seems reasonable"}]
            assert rounds <= MAX_POLICY_CLARIFICATION_ROUNDS, "asked more questions than the cap allows"

    assert rounds == MAX_POLICY_CLARIFICATION_ROUNDS
    assert draft["max_transaction_amount"] == 150


async def test_a_question_past_the_round_cap_fails_loudly_instead_of_looping(monkeypatch):
    """If the model ignores the forced-final-answer nudge and tries to ask
    yet another question anyway, that must not be honored as a valid pause
    (it would let a stubborn model stall this forever) - it should instead
    be treated as an incomplete draft and fail with a clear error."""
    replies = [json.dumps({"type": "clarifying_question", "question": f"Q{i}?"})
               for i in range(MAX_POLICY_CLARIFICATION_ROUNDS + 1)]
    monkeypatch.setattr(policy_drafting, "_client_and_settings", _fake_client_sequence(replies))

    conversation = [{"role": "user", "content": "Manage our SaaS subscriptions."}]
    try:
        for _ in range(MAX_POLICY_CLARIFICATION_ROUNDS):
            try:
                await draft_policy_step(conversation)
                assert False, "expected clarification rounds to be honored up to the cap"
            except PolicyNeedsClarification as clar:
                conversation = [*clar.conversation, {"role": "user", "content": "sure"}]
        # One more call: the model asks AGAIN despite the forced-final nudge.
        await draft_policy_step(conversation)
        assert False, "expected a PolicyDraftError once the model ignored the round cap"
    except PolicyDraftError:
        pass


def test_draft_policy_endpoint_surfaces_needs_clarification(monkeypatch):
    """The HTTP layer must forward the pause as a structured response the
    frontend can act on, not swallow it into a 200 with a half-finished
    draft or a confusing error."""
    question_reply = json.dumps({
        "type": "clarifying_question",
        "question": "Which specific SaaS tools should this agent manage?",
    })
    monkeypatch.setattr(policy_drafting, "_client_and_settings", _fake_client_sequence([question_reply]))

    with TestClient(app) as client:
        resp = client.post("/agents/draft-policy", json={"instructions": "Manage our SaaS subscriptions."})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "needs_clarification"
        assert "Which specific SaaS tools" in body["question"]
        assert isinstance(body["conversation"], list)

        # Continuing with the human's answer, using the returned conversation
        # verbatim, must be accepted by the same endpoint.
        draft_reply = json.dumps({"type": "policy_draft", "draft": FULL_DRAFT})
        monkeypatch.setattr(policy_drafting, "_client_and_settings", _fake_client_sequence([draft_reply]))
        resp2 = client.post(
            "/agents/draft-policy",
            json={"conversation": body["conversation"], "answer": "Figma, Notion, and Slack."},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["status"] == "ready"
        assert body2["draft"]["allowed_categories"] == ["software", "subscriptions"]
