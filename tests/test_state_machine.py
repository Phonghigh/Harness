import pytest

from harness.schemas.task import TaskStatus
from harness.state_machine import (
    InvalidTransitionError,
    WrongStateError,
    assert_command_allowed,
    validate_transition,
)


class TestValidTransitions:
    def test_intake_to_interrogating(self):
        validate_transition(TaskStatus.INTAKE, TaskStatus.INTERROGATING)

    def test_interrogating_to_waiting(self):
        validate_transition(TaskStatus.INTERROGATING, TaskStatus.WAITING_FOR_DECISIONS)

    def test_waiting_to_approved(self):
        validate_transition(TaskStatus.WAITING_FOR_DECISIONS, TaskStatus.DECISIONS_APPROVED)

    def test_approved_to_contract_ready(self):
        validate_transition(TaskStatus.DECISIONS_APPROVED, TaskStatus.CONTRACT_READY)

    def test_contract_ready_to_implementing(self):
        validate_transition(TaskStatus.CONTRACT_READY, TaskStatus.IMPLEMENTING)

    def test_implementing_to_checking(self):
        validate_transition(TaskStatus.IMPLEMENTING, TaskStatus.CHECKING_COMPLIANCE)

    def test_checking_to_validating(self):
        validate_transition(TaskStatus.CHECKING_COMPLIANCE, TaskStatus.VALIDATING)

    def test_checking_back_to_implementing(self):
        validate_transition(TaskStatus.CHECKING_COMPLIANCE, TaskStatus.IMPLEMENTING)

    def test_validating_to_done(self):
        validate_transition(TaskStatus.VALIDATING, TaskStatus.DONE)

    def test_validating_back_to_implementing(self):
        validate_transition(TaskStatus.VALIDATING, TaskStatus.IMPLEMENTING)


class TestInvalidTransitions:
    def test_cannot_skip_interrogation(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(TaskStatus.INTAKE, TaskStatus.IMPLEMENTING)

    def test_cannot_skip_from_intake_to_done(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(TaskStatus.INTAKE, TaskStatus.DONE)

    def test_cannot_go_backward_from_approved(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(TaskStatus.DECISIONS_APPROVED, TaskStatus.INTAKE)

    def test_done_is_terminal(self):
        for state in TaskStatus:
            if state != TaskStatus.DONE:
                with pytest.raises(InvalidTransitionError):
                    validate_transition(TaskStatus.DONE, state)

    def test_cannot_skip_waiting_for_decisions(self):
        with pytest.raises(InvalidTransitionError):
            validate_transition(TaskStatus.INTERROGATING, TaskStatus.DECISIONS_APPROVED)


class TestCommandRequirements:
    def test_interrogate_requires_intake(self):
        assert_command_allowed("interrogate", TaskStatus.INTAKE)

    def test_interrogate_fails_on_wrong_state(self):
        with pytest.raises(WrongStateError):
            assert_command_allowed("interrogate", TaskStatus.WAITING_FOR_DECISIONS)

    def test_answer_requires_waiting(self):
        assert_command_allowed("answer", TaskStatus.WAITING_FOR_DECISIONS)

    def test_approve_requires_waiting(self):
        assert_command_allowed("approve", TaskStatus.WAITING_FOR_DECISIONS)

    def test_contract_requires_decisions_approved(self):
        assert_command_allowed("contract", TaskStatus.DECISIONS_APPROVED)

    def test_implement_requires_contract_ready(self):
        assert_command_allowed("implement", TaskStatus.CONTRACT_READY)

    def test_check_requires_implementing(self):
        assert_command_allowed("check", TaskStatus.IMPLEMENTING)

    def test_validate_requires_checking_or_validating(self):
        assert_command_allowed("validate", TaskStatus.CHECKING_COMPLIANCE)
        assert_command_allowed("validate", TaskStatus.VALIDATING)

    def test_remember_requires_done(self):
        assert_command_allowed("remember", TaskStatus.DONE)

    def test_remember_fails_on_implementing(self):
        with pytest.raises(WrongStateError):
            assert_command_allowed("remember", TaskStatus.IMPLEMENTING)
