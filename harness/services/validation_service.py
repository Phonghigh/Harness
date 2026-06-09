import json
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError

from harness.db import Database, now_iso
from harness.llm import LLMAdapter, LLMOutputError, extract_json_block, load_prompt
from harness.schemas.compliance import ComplianceReport, Violation, ViolationType
from harness.schemas.task import TaskStatus
from harness.state_machine import assert_command_allowed, transition


class _LLMCheckResult(BaseModel):
    passed: bool
    violations: list[Violation]
    summary: str
    llm_review: str | None = None


def _extract_files_from_patch(patch: str) -> list[str]:
    return re.findall(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)


def _rule_based_check(contract: dict, patch_content: str) -> list[Violation]:
    violations: list[Violation] = []

    modified = _extract_files_from_patch(patch_content)
    allowed = json.loads(contract["allowed_files_json"])
    for f in modified:
        if f not in allowed:
            violations.append(Violation(
                type=ViolationType.SCOPE_VIOLATION,
                severity="error",
                description=f"File '{f}' not in contract allowed_files",
            ))

    forbidden = json.loads(contract["forbidden_json"])
    added_lines = [
        line[1:]
        for line in patch_content.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    for pattern in forbidden:
        for i, line in enumerate(added_lines):
            if pattern.lower() in line.lower():
                violations.append(Violation(
                    type=ViolationType.FORBIDDEN_PATTERN,
                    severity="error",
                    description=f"Forbidden pattern '{pattern}' in added lines",
                    line_ref=f"added line ~{i + 1}",
                ))

    spec = json.loads(contract["spec_json"])
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


def _llm_semantic_check(
    contract: dict,
    patch_content: str,
    rule_violations: list[Violation],
    llm: LLMAdapter,
) -> _LLMCheckResult:
    rule_findings_text = "\n".join(
        f"[{v.severity.upper()}] {v.type}: {v.description}"
        for v in rule_violations
    ) or "(none)"

    contract_data = {
        "id": contract["id"],
        "scope": contract["scope"],
        "allowed_files": json.loads(contract["allowed_files_json"]),
        "forbidden": json.loads(contract["forbidden_json"]),
        "spec": json.loads(contract["spec_json"]),
    }

    template = load_prompt("compliance_checker")
    parts = template.split("---USER---", 1)
    system = parts[0].strip()
    user = parts[1].strip()
    user = user.replace("{contract_json}", json.dumps(contract_data, indent=2))
    user = user.replace("{patch_content}", patch_content)
    user = user.replace("{rule_findings}", rule_findings_text)

    raw_response = llm.complete(system, user)
    raw = extract_json_block(raw_response)

    try:
        return _LLMCheckResult.model_validate_json(raw)
    except ValidationError as e:
        raise LLMOutputError(f"LLM returned invalid compliance result: {e}") from e


def check_compliance(
    task: dict,
    contract: dict,
    patch_content: str,
    harness_dir: Path,
    llm: LLMAdapter,
    db: Database,
) -> ComplianceReport:
    assert_command_allowed("check", TaskStatus(task["status"]))
    transition(task, TaskStatus.CHECKING_COMPLIANCE, db)

    rule_violations = _rule_based_check(contract, patch_content)
    rule_passed = not any(v.severity == "error" for v in rule_violations)

    llm_result = _llm_semantic_check(contract, patch_content, rule_violations, llm)

    all_violations = rule_violations + llm_result.violations
    passed = rule_passed and llm_result.passed

    patch_file = str(harness_dir / "patches" / f"{contract['id']}.diff")

    report = ComplianceReport(
        contract_id=contract["id"],
        patch_file=patch_file,
        passed=passed,
        violations=all_violations,
        summary=llm_result.summary,
        rule_based_passed=rule_passed,
        llm_review=llm_result.llm_review,
    )

    latest_patch = db.get_latest_patch(contract["id"])
    report_id = db.new_compliance_report_id()
    db.create_compliance_report({
        "id": report_id,
        "contract_id": contract["id"],
        "patch_id": latest_patch["id"] if latest_patch else "UNKNOWN",
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
