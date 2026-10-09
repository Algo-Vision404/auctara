"""Centralized, deterministic transaction state machine.

No other module may assign an arbitrary transaction `state` value. All
transitions must go through `transition()`, which validates the move
against the allowed-edges graph below.
"""
from __future__ import annotations


class InvalidTransition(Exception):
    pass


STATES = {
    "CREATED",
    "RESEARCHING",
    "NEEDS_INPUT",
    "PROPOSED",
    "POLICY_CHECK",
    "BLOCKED",
    "AWAITING_APPROVAL",
    "AUTHORIZED",
    "VERIFYING",
    "CAPTURED",
    "VOIDED",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
}

TERMINAL_STATES = {"BLOCKED", "COMPLETED", "VOIDED", "FAILED", "CANCELLED"}

# CANCELLED is distinct from every other terminal state: it means the agent
# that owned this transaction was retired or deleted while the transaction
# was still in flight (see orchestrator.retire_agent/delete_agent), not that
# anything about the transaction itself failed, was blocked by policy, or
# was voided for a price mismatch. It is reachable from every non-terminal
# state except CAPTURED: once PayPal has actually captured the money, the
# payment is effectively done and must run through to COMPLETED rather than
# being cancelled out from under a real charge.
ALLOWED_EDGES: dict[str, set[str]] = {
    "CREATED": {"RESEARCHING", "FAILED", "CANCELLED"},
    # BLOCKED here specifically covers the agent itself declining a task as
    # outside its assigned purpose/directive (see
    # orchestrator.OutOfScopeError), before any proposal is ever produced.
    # It is a deliberate refusal, not a research failure, so it ends in the
    # same terminal state a deterministic policy block does rather than
    # FAILED.
    # NEEDS_INPUT covers the agent's next message being plain conversational
    # text (a clarifying question, or a "here's the closest match I found,
    # want it?" check-in) instead of a tool call. Not a failure: the
    # research loop pauses here, with its full conversation persisted, until
    # a human replies via POST /tasks/{id}/respond, which resumes the same
    # loop back in RESEARCHING (see orchestrator.resume_task).
    "RESEARCHING": {"PROPOSED", "FAILED", "BLOCKED", "CANCELLED", "NEEDS_INPUT"},
    "NEEDS_INPUT": {"RESEARCHING", "FAILED", "CANCELLED"},
    "PROPOSED": {"POLICY_CHECK", "FAILED", "CANCELLED"},
    "POLICY_CHECK": {"BLOCKED", "AWAITING_APPROVAL", "AUTHORIZED", "FAILED", "CANCELLED"},
    "AWAITING_APPROVAL": {"AUTHORIZED", "BLOCKED", "FAILED", "CANCELLED"},
    "AUTHORIZED": {"VERIFYING", "FAILED", "CANCELLED"},
    "VERIFYING": {"CAPTURED", "VOIDED", "FAILED", "CANCELLED"},
    "CAPTURED": {"COMPLETED", "FAILED"},
    "VOIDED": set(),
    "COMPLETED": set(),
    "BLOCKED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}


def can_transition(current: str, target: str) -> bool:
    if current not in STATES or target not in STATES:
        return False
    return target in ALLOWED_EDGES.get(current, set())


def transition(current: str, target: str) -> str:
    """Validate and return the target state, or raise InvalidTransition."""
    if current == target:
        raise InvalidTransition(f"Transaction already in state {current}")
    if not can_transition(current, target):
        raise InvalidTransition(f"Cannot move from {current} to {target}")
    return target
