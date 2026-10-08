import pytest

from app.state_machine import InvalidTransition, can_transition, transition


def test_valid_full_allow_flow():
    path = ["CREATED", "RESEARCHING", "PROPOSED", "POLICY_CHECK", "AUTHORIZED",
            "VERIFYING", "CAPTURED", "COMPLETED"]
    current = path[0]
    for target in path[1:]:
        current = transition(current, target)
    assert current == "COMPLETED"


def test_valid_approval_flow():
    path = ["PROPOSED", "POLICY_CHECK", "AWAITING_APPROVAL", "AUTHORIZED", "VERIFYING", "CAPTURED", "COMPLETED"]
    current = path[0]
    for target in path[1:]:
        current = transition(current, target)
    assert current == "COMPLETED"


def test_blocked_flow():
    current = transition("PROPOSED", "POLICY_CHECK")
    current = transition(current, "BLOCKED")
    assert current == "BLOCKED"


def test_void_flow():
    current = "VERIFYING"
    current = transition(current, "VOIDED")
    assert current == "VOIDED"


def test_invalid_transition_raises():
    with pytest.raises(InvalidTransition):
        transition("CREATED", "CAPTURED")


def test_cannot_leave_terminal_state():
    assert can_transition("COMPLETED", "CAPTURED") is False
    assert can_transition("BLOCKED", "AUTHORIZED") is False
    with pytest.raises(InvalidTransition):
        transition("COMPLETED", "FAILED")


def test_any_active_state_can_fail():
    for state in ["CREATED", "RESEARCHING", "PROPOSED", "POLICY_CHECK", "AWAITING_APPROVAL",
                   "AUTHORIZED", "VERIFYING", "CAPTURED"]:
        assert can_transition(state, "FAILED") is True


def test_same_state_rejected():
    with pytest.raises(InvalidTransition):
        transition("CREATED", "CREATED")
