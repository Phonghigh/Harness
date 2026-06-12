import json
import pytest

from harness.db import now_iso
from harness.runtime import PauseReason, RuntimeResult, run_until_pause
from harness.schemas.task import TaskStatus
from harness.services.decision_service import generate_stub_decisions
from harness.services.task_service import create_task
from harness.state_machine import transition


def _make_stub_contract(task_id: str, db) -> dict:
    """Insert a minimal stub contract and return it as a dict."""
    from harness.db import now_iso
    contract_id = db.new_contract_id()
    c = {
        "id": contract_id,
        "task_id": task_id,
        "scope": "stub scope",
        "allowed_files_json": json.dumps(["src/stub.py"]),
        "forbidden_json": json.dumps([]),
        "spec_json": json.dumps({
            "summary": "stub",
            "files": [{"path": "src/stub.py", "action": "create", "description": "stub"}],
            "constraints": [],
            "acceptance_criteria": [],
        }),
        "status": "approved",
        "decision_ids_json": json.dumps([]),
        "created_at": now_iso(),
    }
    db.create_contract(c)
    return c


def _make_stub_patch(contract_id: str, db) -> dict:
    """Insert a minimal stub patch and return it as a dict."""
    patch_id = db.new_patch_id()
    p = {
        "id": patch_id,
        "contract_id": contract_id,
        "diff_text": "--- a/src/stub.py\n+++ b/src/stub.py\n@@ -0,0 +1 @@\n+# stub\n",
        "status": "generated",
        "created_at": now_iso(),
    }
    db.create_patch(p)
    return p


class TestRunUntilPauseLLMUnavailable:
    def test_returns_llm_unavailable_at_intake(self, task, db, config):
        result = run_until_pause(task["id"], db.db_path.parent, config, db, llm=None)
        assert result.paused_at == PauseReason.LLM_UNAVAILABLE
        assert result.task_id == task["id"]

    def test_returns_llm_unavailable_at_decisions_approved(self, db, config):
        task = create_task("test task", db)
        decisions = generate_stub_decisions(task, db)
        task = dict(db.get_task(task["id"]))
        for d in decisions:
            from harness.services.decision_service import answer_decision
            answer_decision(d["id"], "answer", task, db)
            task = dict(db.get_task(task["id"]))
        all_ids = [d["id"] for d in decisions]
        from harness.services.decision_service import approve_decisions
        approve_decisions(all_ids, task, db)
        task = dict(db.get_task(task["id"]))
        assert task["status"] == TaskStatus.DECISIONS_APPROVED

        result = run_until_pause(task["id"], db.db_path.parent, config, db, llm=None)
        assert result.paused_at == PauseReason.LLM_UNAVAILABLE


class TestRunUntilPausePatchApproval:
    def test_pauses_at_patch_approval_required(self, db, config, mock_llm):
        """Full flow from INTAKE to IMPLEMENTING should pause at PATCH_APPROVAL_REQUIRED."""
        task = create_task("test task for runtime", db)
        task_id = task["id"]

        # Mock: interrogator returns valid DecisionMap JSON
        mock_llm.complete.return_value = json.dumps({
            "decisions": [
                {
                    "category": "data_model",
                    "question": "What fields?",
                    "options": ["id, name", "id, name, ts"],
                    "recommendation": "id, name",
                }
            ],
            "rationale": "simple",
        })

        # Run until WAITING_FOR_DECISIONS → needs auto-answer LLM call too
        # Provide consistent response for all LLM calls
        mock_llm.complete.side_effect = [
            # interrogator call
            json.dumps({
                "decisions": [
                    {
                        "category": "data_model",
                        "question": "What fields?",
                        "options": ["id, name", "id, name, ts"],
                        "recommendation": "id, name",
                    }
                ],
                "rationale": "simple",
            }),
            # decision_answerer call
            json.dumps({"selected_answer": "id, name", "confidence": "high", "rationale": "simple"}),
            # contract_builder call
            json.dumps({
                "summary": "Create stub entity",
                "files": [{"path": "src/entity.py", "action": "create", "description": "entity"}],
                "constraints": [],
                "acceptance_criteria": ["entity exists"],
            }),
            # syntax_executor call
            "--- a/src/entity.py\n+++ b/src/entity.py\n@@ -0,0 +1 @@\n+# entity\n",
        ]

        result = run_until_pause(task_id, db.db_path.parent, config, db, mock_llm)
        assert result.task_id == task_id
        assert result.paused_at == PauseReason.PATCH_APPROVAL_REQUIRED
        assert result.patch_file is not None
        assert result.contract_id is not None


class TestRunUntilPauseDone:
    def test_returns_done_when_validating_with_no_commands(self, db, config):
        """Starting from VALIDATING with no validate_commands should return DONE."""
        task = create_task("done test", db)
        task_id = task["id"]

        # Manually drive task to VALIDATING through all states
        task_dict = dict(task)
        for state in [
            TaskStatus.INTERROGATING,
            TaskStatus.WAITING_FOR_DECISIONS,
            TaskStatus.DECISIONS_APPROVED,
            TaskStatus.WAITING_FOR_CONTRACT_APPROVAL,
            TaskStatus.CONTRACT_READY,
            TaskStatus.WAITING_FOR_PATCH_APPROVAL,
            TaskStatus.IMPLEMENTING,
            TaskStatus.CHECKING_COMPLIANCE,
            TaskStatus.VALIDATING,
        ]:
            transition(task_dict, state, db)
            task_dict["status"] = state

        result = run_until_pause(task_id, db.db_path.parent, config, db, llm=None)
        assert result.paused_at == PauseReason.DONE
        final_task = db.get_task(task_id)
        assert final_task["status"] == TaskStatus.DONE


class TestRunUntilPauseComplianceRetry:
    def test_returns_compliance_failed_after_max_retries(self, db, config, mock_llm, tmp_path):
        """Runtime should give up after max_compliance_retries compliance failures."""
        task = create_task("compliance retry test", db)
        task_id = task["id"]

        # Manually drive to IMPLEMENTING with a contract and patch
        task_dict = dict(task)
        for state in [
            TaskStatus.INTERROGATING,
            TaskStatus.WAITING_FOR_DECISIONS,
            TaskStatus.DECISIONS_APPROVED,
            TaskStatus.WAITING_FOR_CONTRACT_APPROVAL,
            TaskStatus.CONTRACT_READY,
            TaskStatus.WAITING_FOR_PATCH_APPROVAL,
            TaskStatus.IMPLEMENTING,
        ]:
            transition(task_dict, state, db)
            task_dict["status"] = state

        contract = _make_stub_contract(task_id, db)
        _make_stub_patch(contract["id"], db)

        # Compliance check always fails — mock LLM returns a failing report
        failing_compliance = json.dumps({
            "passed": False,
            "violations": [{"type": "scope_violation", "severity": "error",
                            "description": "bad file", "line_ref": None}],
            "summary": "failed",
            "llm_review": "bad",
        })
        # reimplement also calls LLM — alternate compliance-fail and reimplement responses
        mock_llm.complete.return_value = failing_compliance

        result = run_until_pause(
            task_id, tmp_path, config, db, mock_llm, max_compliance_retries=2
        )
        assert result.paused_at == PauseReason.COMPLIANCE_FAILED
        assert result.compliance_retries >= 2
