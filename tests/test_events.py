"""Tests for event logging: db methods, state_machine emission, and event ID format."""
import pytest

from harness.db import Database, now_iso
from harness.schemas.task import TaskStatus
from harness.services.task_service import create_task
from harness.state_machine import transition


class TestEventIdFormat:
    def test_sequential_ids_are_ev_prefixed(self, db, task):
        assert db.new_event_id() == "EV00001"
        db.log_event({
            "id": "EV00001",
            "task_id": task["id"],
            "event_type": "state_transition",
            "from_state": None, "to_state": None,
            "tool_name": None, "prompt_name": None,
            "input_hash": None, "output_hash": None,
            "duration_ms": None, "metadata_json": None,
            "created_at": now_iso(),
        })
        assert db.new_event_id() == "EV00002"


class TestLogAndGetEvents:
    def test_get_events_filters_by_task_id(self, db, task):
        """Events are scoped to task_id; an unknown task_id returns empty."""
        db.log_event({
            "id": "EV00001", "task_id": task["id"],
            "event_type": "state_transition",
            "from_state": "INTAKE", "to_state": "INTERROGATING",
            "tool_name": None, "prompt_name": None,
            "input_hash": None, "output_hash": None,
            "duration_ms": None, "metadata_json": None,
            "created_at": now_iso(),
        })
        db.log_event({
            "id": "EV00002", "task_id": task["id"],
            "event_type": "llm_call",
            "from_state": None, "to_state": None,
            "tool_name": None, "prompt_name": "interrogator",
            "input_hash": "abc123", "output_hash": "def456",
            "duration_ms": 1200, "metadata_json": None,
            "created_at": now_iso(),
        })
        events = db.get_events(task["id"])
        assert len(events) == 2
        assert events[0]["event_type"] == "state_transition"
        assert events[1]["event_type"] == "llm_call"
        assert events[1]["prompt_name"] == "interrogator"
        assert events[1]["duration_ms"] == 1200
        assert db.get_events("T_NONE") == []


class TestStateTransitionEmitsEvent:
    def test_transition_records_event_in_db(self, db):
        task = create_task("event trace test", db)
        task_dict = dict(task)
        assert db.count_events() == 0

        transition(task_dict, TaskStatus.INTERROGATING, db)

        events = db.get_events(task["id"])
        assert len(events) == 1
        ev = dict(events[0])
        assert ev["event_type"] == "state_transition"
        assert ev["from_state"] == TaskStatus.INTAKE.value
        assert ev["to_state"] == TaskStatus.INTERROGATING.value
        assert ev["task_id"] == task["id"]
