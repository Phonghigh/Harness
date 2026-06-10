import json
import pytest

from harness.db import now_iso
from harness.services.memory_service import _slugify, inject_project_memory, search_memory


class TestSlugify:
    def test_basic(self):
        assert _slugify("Use DTO pattern") == "use_dto_pattern"

    def test_truncates_at_60(self):
        long_text = "a" * 100
        assert len(_slugify(long_text)) <= 60

    def test_strips_special_chars(self):
        result = _slugify("Use JWT (RS256) for auth!")
        assert " " not in result
        assert "(" not in result
        assert ")" not in result
        assert "!" not in result


class TestInjectProjectMemory:
    def test_empty_returns_none_string(self, db):
        result = inject_project_memory(db)
        assert result == "(none)"

    def test_formats_memories(self, db, config):
        db.upsert_memory({
            "id": "M00000001",
            "type": "project_standard",
            "scope": "test_project",
            "key": "dto_policy",
            "value_json": json.dumps({"lesson": "Use DTOs", "context": "API responses"}),
            "source_task_id": None,
            "applied_count": 0,
            "last_applied_at": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        result = inject_project_memory(db)
        assert "dto_policy" in result
        assert result != "(none)"

    def test_increments_applied_count(self, db, config):
        db.upsert_memory({
            "id": "M00000002",
            "type": "lesson",
            "scope": "test_project",
            "key": "test_key",
            "value_json": json.dumps({"lesson": "A lesson", "context": "ctx"}),
            "source_task_id": None,
            "applied_count": 0,
            "last_applied_at": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        inject_project_memory(db)
        mem = db.list_memory()[0]
        assert mem["applied_count"] == 1


class TestSearchMemory:
    def test_finds_by_key(self, db, config):
        db.upsert_memory({
            "id": "M00000003",
            "type": "lesson",
            "scope": "test_project",
            "key": "jwt_auth_policy",
            "value_json": json.dumps({"lesson": "Use RS256", "context": "auth"}),
            "source_task_id": None,
            "applied_count": 0,
            "last_applied_at": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        results = search_memory(db, "jwt")
        assert len(results) >= 1

    def test_finds_by_value(self, db, config):
        db.upsert_memory({
            "id": "M00000004",
            "type": "lesson",
            "scope": "test_project",
            "key": "some_key",
            "value_json": json.dumps({"lesson": "Use repository pattern", "context": "data"}),
            "source_task_id": None,
            "applied_count": 0,
            "last_applied_at": None,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        })
        results = search_memory(db, "repository")
        assert len(results) >= 1

    def test_no_match_returns_empty(self, db):
        results = search_memory(db, "xyznotfound")
        assert results == []
