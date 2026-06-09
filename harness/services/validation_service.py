import json
import re
import subprocess
from pathlib import Path

from pydantic import ValidationError

from harness.db import Database, now_iso
from harness.llm import LLMAdapter, extract_json_block, load_prompt, split_prompt
from harness.schemas.compliance import ComplianceReport, Violation, ViolationType
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition


def check_compliance(
    task: dict,
    contract: dict,
    patch: dict,
    db: Database,
    llm: LLMAdapter | None = None,
) -> ComplianceReport:
    assert_command_allowed("check", TaskStatus(task["status"]))
    transition(task, TaskStatus.CHECKING_COMPLIANCE, db)

    patch_content = patch["diff_text"]
    allowed_files = json.loads(contract["allowed_files_json"])
    forbidden_patterns = json.loads(contract["forbidden_json"])
    spec = json.loads(contract["spec_json"])

    # Phase 1: rule-based checks
    rule_violations = _rule_based_check(patch_content, allowed_files, forbidden_patterns, spec)
    rule_passed = not any(v.severity == "error" for v in rule_violations)

    # Phase 2: LLM semantic check
    llm_violations: list[Violation] = []
    llm_review: str | None = None
    llm_passed = True

    if llm is not None:
        rule_findings_text = (
            "\n".join(f"- [{v.severity.upper()}] {v.type}: {v.description}" for v in rule_violations)
            or "No rule-based violations found."
        )
        template = load_prompt("compliance_checker")
        system, user_template = split_prompt(template)
        user = (
            user_template
            .replace("{scope}", contract["scope"])
            .replace("{allowed_files}", "\n".join(f"  {f}" for f in allowed_files))
            .replace("{spec}", json.dumps(spec, indent=2))
            .replace("{rule_findings}", rule_findings_text)
            .replace("{diff}", patch_content[:8000])  # cap to avoid token overflow
        )
        response = llm.complete(system, user)
        raw = extract_json_block(response.content)
        try:
            llm_result = _LLMComplianceResult.model_validate_json(raw)
            llm_passed = llm_result.passed
            llm_review = llm_result.summary
            llm_violations = [
                Violation(
                    type=ViolationType(v.type),
                    severity=v.severity,
                    description=v.description,
                    line_ref=v.line_ref,
                )
                for v in llm_result.violations
            ]
        except (ValidationError, ValueError):
            llm_review = "[LLM review parse error — treated as pass]"
    else:
        llm_review = "[STUB] LLM semantic review skipped — no API key."

    all_violations = rule_violations + llm_violations
    passed = rule_passed and llm_passed

    patch_file = f".harness/patches/{contract['id']}.diff"
    report = ComplianceReport(
        contract_id=contract["id"],
        patch_file=patch_file,
        passed=passed,
        violations=all_violations,
        summary=llm_review or ("PASS" if passed else "FAIL — see violations"),
        rule_based_passed=rule_passed,
        llm_review=llm_review,
    )

    db.create_compliance_report({
        "id": db.new_compliance_report_id(),
        "contract_id": contract["id"],
        "patch_id": patch["id"],
        "passed": int(passed),
        "violations_json": json.dumps([v.model_dump() for v in all_violations]),
        "summary": report.summary,
        "created_at": now_iso(),
    })

    checking = {"id": task["id"], "status": TaskStatus.CHECKING_COMPLIANCE}
    if passed:
        transition(checking, TaskStatus.VALIDATING, db)
    else:
        transition(checking, TaskStatus.IMPLEMENTING, db)

    return report


def run_validate(task: dict, validate_commands: list[str], db: Database) -> bool:
    assert_command_allowed("validate", TaskStatus(task["status"]))

    current = TaskStatus(task["status"])
    if current == TaskStatus.CHECKING_COMPLIANCE:
        transition(task, TaskStatus.VALIDATING, db)
        task = dict(db.get_task(task["id"]))

    if not validate_commands:
        transition({"id": task["id"], "status": TaskStatus.VALIDATING}, TaskStatus.DONE, db)
        return True

    all_passed = True
    for cmd in validate_commands:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            all_passed = False

    validating = {"id": task["id"], "status": TaskStatus.VALIDATING}
    if all_passed:
        transition(validating, TaskStatus.DONE, db)
    else:
        transition(validating, TaskStatus.IMPLEMENTING, db)
    return all_passed


# --- Rule-based checks ---

def _extract_files_from_patch(patch: str) -> list[str]:
    return re.findall(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)


def _rule_based_check(
    patch: str,
    allowed_files: list[str],
    forbidden_patterns: list[str],
    spec: dict,
) -> list[Violation]:
    violations: list[Violation] = []
    modified = _extract_files_from_patch(patch)

    # Check 1: file scope
    for f in modified:
        if f not in allowed_files:
            violations.append(Violation(
                type=ViolationType.SCOPE_VIOLATION,
                severity="error",
                description=f"File '{f}' not in contract allowed_files",
            ))

    # Check 2: forbidden patterns in added lines
    added_lines = [
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    for pattern in forbidden_patterns:
        for i, line in enumerate(added_lines):
            if pattern.lower() in line.lower():
                violations.append(Violation(
                    type=ViolationType.FORBIDDEN_PATTERN,
                    severity="error",
                    description=f"Forbidden pattern '{pattern}' found in added lines",
                    line_ref=f"added line ~{i + 1}",
                ))

    # Check 3: coverage — every spec file should appear in the patch
    modified_set = set(modified)
    for file_spec in spec.get("files", []):
        if file_spec.get("action") in ("create", "modify"):
            if file_spec["path"] not in modified_set:
                violations.append(Violation(
                    type=ViolationType.MISSING_SPEC,
                    severity="warning",
                    description=f"Contract spec file '{file_spec['path']}' not found in patch",
                ))

    return violations


# --- LLM output models ---

from pydantic import BaseModel  # noqa: E402 — intentional late import for readability


class _LLMViolation(BaseModel):
    type: str
    severity: str
    description: str
    line_ref: str | None = None


class _LLMComplianceResult(BaseModel):
    passed: bool
    violations: list[_LLMViolation] = []
    summary: str
