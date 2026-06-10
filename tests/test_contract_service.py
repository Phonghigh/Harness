import json
import pytest

from harness.schemas.task import TaskStatus
from harness.services.contract_service import build_contract
from harness.services.decision_service import answer_decision, approve_decisions, generate_stub_decisions
from harness.state_machine import WrongStateError


def _task_at_decisions_approved(task, db):
    decisions = generate_stub_decisions(task, db)
    waiting = dict(db.get_task(task["id"]))
    for d in decisions:
        answer_decision(d["id"], "approved answer", waiting, db)
    all_ids = [d["id"] for d in decisions]
    approve_decisions(all_ids, waiting, db)
    return dict(db.get_task(task["id"]))


class TestBuildContractStub:
    def test_creates_contract(self, task, db):
        approved_task = _task_at_decisions_approved(task, db)
        contract = build_contract(approved_task, db, llm=None)
        assert contract["id"].startswith("C")
        assert contract["task_id"] == task["id"]

    def test_transitions_task_to_contract_ready(self, task, db):
        approved_task = _task_at_decisions_approved(task, db)
        build_contract(approved_task, db, llm=None)
        updated = db.get_task(task["id"])
        assert updated["status"] == TaskStatus.CONTRACT_READY

    def test_contract_has_allowed_files(self, task, db):
        approved_task = _task_at_decisions_approved(task, db)
        contract = build_contract(approved_task, db, llm=None)
        allowed = json.loads(contract["allowed_files_json"])
        assert isinstance(allowed, list)
        assert len(allowed) >= 1

    def test_contract_tracks_decision_ids(self, task, db):
        approved_task = _task_at_decisions_approved(task, db)
        contract = build_contract(approved_task, db, llm=None)
        decision_ids = json.loads(contract["decision_ids_json"])
        assert isinstance(decision_ids, list)
        assert len(decision_ids) >= 1

    def test_cannot_build_contract_before_decisions_approved(self, task, db):
        with pytest.raises(WrongStateError):
            build_contract(task, db, llm=None)
