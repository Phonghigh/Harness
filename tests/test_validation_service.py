import json
import pytest

from harness.schemas.compliance import ViolationType
from harness.services.validation_service import _extract_files_from_patch, _rule_based_check


SAMPLE_PATCH = """\
--- a/src/main.py
+++ b/src/main.py
@@ -0,0 +1,5 @@
+def hello():
+    return "hello"
+
+def world():
+    return "world"
"""

SAMPLE_CONTRACT = {
    "id": "C001",
    "allowed_files_json": json.dumps(["src/main.py"]),
    "forbidden_json": json.dumps(["TODO", "print("]),
    "spec_json": json.dumps({
        "summary": "Add hello function",
        "files": [{"path": "src/main.py", "action": "create", "description": "Main module"}],
        "constraints": [],
        "acceptance_criteria": [],
    }),
}


class TestExtractFilesFromPatch:
    def test_extracts_modified_file(self):
        files = _extract_files_from_patch(SAMPLE_PATCH)
        assert "src/main.py" in files

    def test_no_dev_null(self):
        patch = "--- /dev/null\n+++ b/src/new.py\n@@ -0,0 +1 @@\n+x=1\n"
        files = _extract_files_from_patch(patch)
        assert "/dev/null" not in files
        assert "src/new.py" in files

    def test_empty_patch(self):
        files = _extract_files_from_patch("")
        assert files == []


class TestRuleBasedCheck:
    def test_passes_clean_patch(self):
        violations = _rule_based_check(SAMPLE_CONTRACT, SAMPLE_PATCH)
        assert all(v.severity != "error" for v in violations)

    def test_detects_scope_violation(self):
        patch = "--- a/src/other.py\n+++ b/src/other.py\n@@ -0,0 +1 @@\n+x=1\n"
        violations = _rule_based_check(SAMPLE_CONTRACT, patch)
        scope = [v for v in violations if v.type == ViolationType.SCOPE_VIOLATION]
        assert len(scope) >= 1
        assert scope[0].severity == "error"

    def test_detects_forbidden_pattern(self):
        patch = "--- a/src/main.py\n+++ b/src/main.py\n@@ -0,0 +1 @@\n+print('debug')\n"
        violations = _rule_based_check(SAMPLE_CONTRACT, patch)
        forbidden = [v for v in violations if v.type == ViolationType.FORBIDDEN_PATTERN]
        assert len(forbidden) >= 1

    def test_warns_on_missing_spec_file(self):
        # Contract wants src/main.py but patch touches a different file
        contract = {
            **SAMPLE_CONTRACT,
            "allowed_files_json": json.dumps(["src/main.py", "src/utils.py"]),
            "spec_json": json.dumps({
                "summary": "test",
                "files": [
                    {"path": "src/main.py", "action": "modify", "description": "main"},
                    {"path": "src/utils.py", "action": "create", "description": "utils"},
                ],
                "constraints": [],
                "acceptance_criteria": [],
            }),
        }
        violations = _rule_based_check(contract, SAMPLE_PATCH)
        missing = [v for v in violations if v.type == ViolationType.MISSING_SPEC]
        assert len(missing) >= 1
        assert missing[0].severity == "warning"
