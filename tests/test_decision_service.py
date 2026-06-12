import json
import pytest

from harness.db import now_iso
from harness.schemas.decision import DecisionStatus
from harness.schemas.task import TaskStatus
from harness.services.decision_service import (
    answer_decision,
    approve_decisions,
    auto_answer_decisions,
    generate_stub_decisions,
    list_decisions,
)
from harness.services.conflict_service import detect_conflicts_fast
from harness.state_machine import WrongStateError, transition


def _move_to_waiting(task, db):
    """Transition task to WAITING_FOR_DECISIONS; returns (refreshed_task, decisions)."""
    decisions = generate_stub_decisions(task, db)
    refreshed = dict(db.get_task(task["id"]))
    return refreshed, decisions


class TestGenerateStubDecisions:
    def test_creates_decisions(self, task, db):
        _, decisions = _move_to_waiting(task, db)
        assert len(decisions) >= 1

    def test_task_transitions_to_waiting(self, task, db):
        _move_to_waiting(task, db)
        updated = db.get_task(task["id"])
        assert updated["status"] == TaskStatus.WAITING_FOR_DECISIONS

    def test_decisions_are_pending(self, task, db):
        _, decisions = _move_to_waiting(task, db)
        for d in decisions:
            assert d["status"] == DecisionStatus.PENDING


class TestAnswerDecision:
    def test_answer_updates_status(self, task, db):
        refreshed, decisions = _move_to_waiting(task, db)
        d = decisions[0]
        answer_decision(d["id"], "My answer", refreshed, db)
        updated = db.get_decision(d["id"])
        assert updated["selected_answer"] == "My answer"
        assert updated["status"] == DecisionStatus.ANSWERED

    def test_answer_requires_waiting_state(self, task, db):
        with pytest.raises(WrongStateError):
            answer_decision("D001", "answer", task, db)


class TestApproveDecisions:
    def test_approve_all_transitions_task(self, task, db):
        refreshed, decisions = _move_to_waiting(task, db)
        for d in decisions:
            answer_decision(d["id"], "answer", refreshed, db)
        task_after_answers = dict(db.get_task(task["id"]))
        all_ids = [d["id"] for d in decisions]
        all_approved, conflicts = approve_decisions(all_ids, task_after_answers, db)
        assert all_approved is True
        updated = db.get_task(task["id"])
        assert updated["status"] == TaskStatus.DECISIONS_APPROVED

    def test_partial_approve_does_not_transition(self, task, db):
        refreshed, decisions = _move_to_waiting(task, db)
        answer_decision(decisions[0]["id"], "answer", refreshed, db)
        task_after_answer = dict(db.get_task(task["id"]))
        all_approved, _ = approve_decisions([decisions[0]["id"]], task_after_answer, db)
        assert all_approved is False
        updated = db.get_task(task["id"])
        assert updated["status"] == TaskStatus.WAITING_FOR_DECISIONS


class TestAutoAnswerDecisions:
    def test_uses_llm_answer_when_valid(self, task, db, mock_llm):
        refreshed, decisions = _move_to_waiting(task, db)
        mock_llm.complete.return_value = (
            '{"selected_answer": "Use DTOs (separate request/response models)", '
            '"confidence": "high", "rationale": "DTOs are the standard here."}'
        )
        answered = auto_answer_decisions(refreshed, decisions, mock_llm, db)
        assert all(d["status"] == DecisionStatus.ANSWERED for d in answered)
        assert answered[0]["selected_answer"] == "Use DTOs (separate request/response models)"

    def test_falls_back_to_recommendation_on_llm_error(self, task, db, mock_llm):
        refreshed, decisions = _move_to_waiting(task, db)
        mock_llm.complete.side_effect = RuntimeError("network failure")
        answered = auto_answer_decisions(refreshed, decisions, mock_llm, db)
        for d in answered:
            assert d["status"] == DecisionStatus.ANSWERED
            assert d["selected_answer"] is not None

    def test_falls_back_to_recommendation_on_invalid_json(self, task, db, mock_llm):
        refreshed, decisions = _move_to_waiting(task, db)
        mock_llm.complete.return_value = "not valid json at all"
        answered = auto_answer_decisions(refreshed, decisions, mock_llm, db)
        for d in answered:
            assert d["status"] == DecisionStatus.ANSWERED

    def test_skips_already_answered_decisions(self, task, db, mock_llm):
        refreshed, decisions = _move_to_waiting(task, db)
        answer_decision(decisions[0]["id"], "pre-answered", refreshed, db)
        refreshed_again = dict(db.get_task(task["id"]))
        decisions_refreshed = [dict(db.get_decision(d["id"])) for d in decisions]
        mock_llm.complete.return_value = (
            '{"selected_answer": "LLM pick", "confidence": "high", "rationale": "r"}'
        )
        auto_answer_decisions(refreshed_again, decisions_refreshed, mock_llm, db)
        # The first decision was pre-answered — LLM should not have been called for it
        assert mock_llm.complete.call_count == len(decisions) - 1


class TestConflictDetection:
    def test_no_conflict_when_no_memories(self):
        decision = {"category": "api_contract", "selected_answer": "use dto pattern"}
        conflicts = detect_conflicts_fast(decision, [])
        assert conflicts == []

    def test_detects_antonym_conflict_same_category(self):
        decision = {
            "category": "api_contract",
            "selected_answer": "entity directly",
        }
        memories = [{
            "key": "api_dto_policy",
            "type": "project_standard",
            "value_json": json.dumps({"category": "api_contract", "lesson": "use dto pattern", "context": "always"}),
        }]
        conflicts = detect_conflicts_fast(decision, memories)
        assert len(conflicts) == 1

    def test_no_conflict_different_category(self):
        decision = {
            "category": "data_model",
            "selected_answer": "entity directly",
        }
        memories = [{
            "key": "api_dto_policy",
            "type": "project_standard",
            "value_json": json.dumps({"category": "api_contract", "lesson": "use dto pattern", "context": "always"}),
        }]
        # Same answer, different category — should NOT conflict
        conflicts = detect_conflicts_fast(decision, memories)
        assert len(conflicts) == 0
