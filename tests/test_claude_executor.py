import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from harness.services.claude_executor import (
    build_impl_prompt,
    capture_diff_staged,
    is_claude_available,
    reset_allowed_files,
    run_claude_implement,
)


class TestIsClaudeAvailable:
    def test_returns_true_when_claude_in_path(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            assert is_claude_available() is True

    def test_returns_false_when_not_in_path(self):
        with patch("shutil.which", return_value=None):
            assert is_claude_available() is False


class TestBuildImplPrompt:
    CONTRACT = {
        "id": "C001",
        "scope": "Add REST endpoints",
        "allowed_files": ["src/Controller.java", "src/Service.java"],
        "forbidden": ["System.out.println", "TODO"],
        "spec": {"files": [{"path": "src/Controller.java", "action": "create"}]},
    }

    def test_contains_contract_id(self):
        prompt = build_impl_prompt(self.CONTRACT)
        assert "C001" in prompt

    def test_contains_all_allowed_files(self):
        prompt = build_impl_prompt(self.CONTRACT)
        assert "src/Controller.java" in prompt
        assert "src/Service.java" in prompt

    def test_contains_forbidden_patterns(self):
        prompt = build_impl_prompt(self.CONTRACT)
        assert "System.out.println" in prompt
        assert "TODO" in prompt

    def test_compliance_feedback_section_present_when_provided(self):
        prompt = build_impl_prompt(self.CONTRACT, compliance_feedback="Missing method X")
        assert "PREVIOUS COMPLIANCE FAILURES" in prompt
        assert "Missing method X" in prompt

    def test_no_compliance_section_when_empty(self):
        prompt = build_impl_prompt(self.CONTRACT, compliance_feedback="")
        assert "PREVIOUS COMPLIANCE FAILURES" not in prompt


class TestRunClaudeImplement:
    def test_returns_true_on_zero_exit(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Done."
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            success, output = run_claude_implement("prompt", tmp_path, timeout=60)
        assert success is True
        assert "Done." in output
        mock_run.assert_called_once_with(
            ["claude", "-p", "prompt"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_returns_false_on_nonzero_exit(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error: file not found"
        with patch("subprocess.run", return_value=mock_result):
            success, output = run_claude_implement("prompt", tmp_path)
        assert success is False
        assert "Error: file not found" in output

    def test_returns_false_on_timeout(self, tmp_path):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 300)):
            success, output = run_claude_implement("prompt", tmp_path, timeout=300)
        assert success is False
        assert "timed out" in output.lower()


class TestCaptureDiffStaged:
    def test_returns_diff_for_existing_files(self, tmp_path):
        (tmp_path / "foo.py").write_text("x = 1")

        add_result = MagicMock(returncode=0)
        diff_result = MagicMock(returncode=0, stdout="diff --git a/foo.py b/foo.py\n+x = 1\n")
        reset_result = MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=[add_result, diff_result, reset_result]) as mock_run:
            diff = capture_diff_staged(tmp_path, ["foo.py"])

        assert "foo.py" in diff
        calls = mock_run.call_args_list
        assert calls[0][0][0][:2] == ["git", "add"]
        assert calls[1][0][0][:3] == ["git", "diff", "--cached"]
        assert calls[2][0][0][:3] == ["git", "reset", "HEAD"]

    def test_returns_empty_when_no_files_exist(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            diff = capture_diff_staged(tmp_path, ["nonexistent.py"])
        assert diff == ""
        mock_run.assert_not_called()


class TestResetAllowedFiles:
    def test_restores_tracked_file(self, tmp_path):
        (tmp_path / "tracked.java").write_text("old content")

        ls_result = MagicMock(returncode=0)
        checkout_result = MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=[ls_result, checkout_result]) as mock_run:
            reset_allowed_files(tmp_path, ["tracked.java"])

        checkout_call = mock_run.call_args_list[1]
        assert "checkout" in checkout_call[0][0]
        assert "tracked.java" in checkout_call[0][0]

    def test_deletes_new_untracked_file(self, tmp_path):
        new_file = tmp_path / "NewController.java"
        new_file.write_text("new content")

        ls_result = MagicMock(returncode=1)

        with patch("subprocess.run", return_value=ls_result):
            reset_allowed_files(tmp_path, ["NewController.java"])

        assert not new_file.exists()
