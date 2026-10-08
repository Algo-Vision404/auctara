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
}

TERMINAL_STATES = {"BLOCKED", "COMPLETED", "VOIDED", "FAILED"}

ALLOWED_EDGES: dict[str, set[str]] = {
    "CREATED": {"RESEARCHING", "FAILED"},
    # BLOCKED here specifically covers the agent itself declining a task as
    # outside its assigned purpose/directive (see
    # orchestrator.OutOfScopeError), before any proposal is ever produced.
    # It is a deliberate refusal, not a research failure, so it ends in the
    # same terminal state a deterministic policy block does rather than
    # FAILED.
    "RESEARCHING": {"PROPOSED", "FAILED", "BLOCKED"},
    "PROPOSED": {"POLICY_CHECK", "FAILED"},
    "POLICY_CHECK": {"BLOCKED", "AWAITING_APPROVAL", "AUTHORIZED", "FAILED"},
    "AWAITING_APPROVAL": {"AUTHORIZED", "BLOCKED", "FAILED"},
    "AUTHORIZED": {"VERIFYING", "FAILED"},
    "VERIFYING": {"CAPTURED", "VOIDED", "FAILED"},
    "CAPTURED": {"COMPLETED", "FAILED"},
    "VOIDED": set(),
    "COMPLETED": set(),
    "BLOCKED": set(),
    "FAILED": set(),
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
