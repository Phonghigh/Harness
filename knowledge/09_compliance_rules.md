# Compliance Rules

Two-phase compliance checking. Rule-based first (deterministic, free), LLM semantic second (catches drift).

## Phase 1: Rule-Based Checks

Run these before calling LLM. If Phase 1 has errors, still run LLM but inject the findings.

### Check 1: File Scope

Parse all `+++ b/<path>` lines from the unified diff. Every modified file must appear in `contract.allowed_files`.

```python
def _extract_files_from_patch(patch: str) -> list[str]:
    import re
    return re.findall(r"^\+\+\+ b/(.+)$", patch, re.MULTILINE)

modified = _extract_files_from_patch(patch_content)
allowed = json.loads(contract["allowed_files_json"])

for f in modified:
    if f not in allowed:
        violations.append(Violation(
            type=ViolationType.SCOPE_VIOLATION,
            severity="error",
            description=f"File '{f}' not in contract allowed_files",
        ))
```

### Check 2: Forbidden Patterns

Scan all added lines (lines starting with `+`, excluding `+++` header lines) for forbidden pattern matches (case-insensitive substring).

```python
forbidden = json.loads(contract["forbidden_json"])
added_lines = [
    line[1:]   # strip leading +
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
```

### Check 3: Coverage

Every `FileSpec` in `contract.spec.files` must have at least one hunk in the diff.

```python
spec = json.loads(contract["spec_json"])
modified_set = set(_extract_files_from_patch(patch_content))

for file_spec in spec["files"]:
    if file_spec["action"] in ("create", "modify"):
        if file_spec["path"] not in modified_set:
            violations.append(Violation(
                type=ViolationType.MISSING_SPEC,
                severity="warning",
                description=f"Contract spec file '{file_spec['path']}' not found in patch",
            ))
```

## Phase 2: LLM Semantic Check

Inject Phase 1 findings into the prompt. LLM checks for:
- Semantic violations (method added that's not in spec)
- Acceptance criteria satisfaction
- Logic that goes beyond the contract description
- Missing spec items not caught by path checks

The LLM output is merged with Phase 1 findings. LLM violations are `warning` by default unless LLM explicitly marks `error`.

## Violation Types

| Type | Phase | Description |
|------|-------|-------------|
| `SCOPE_VIOLATION` | 1 | File not in contract `allowed_files` |
| `FORBIDDEN_PATTERN` | 1 | Pattern from `forbidden` list found in added lines |
| `MISSING_SPEC` | 1 | Contract file not present in patch |
| `EXTRA_SCOPE` | 2 | LLM detected logic beyond contract spec |

## Severity

| Severity | Blocks progression? |
|----------|---------------------|
| `error` | Yes — task returns to IMPLEMENTING |
| `warning` | No — surfaced but does not block |

## Pass/Fail Logic

```python
passed = (
    not any(v.severity == "error" for v in rule_violations)
    and llm_result.passed
)
```

## ComplianceReport Schema

```python
class ComplianceReport(BaseModel):
    contract_id: str
    patch_file: str
    passed: bool
    violations: list[Violation]
    summary: str
    rule_based_passed: bool
    llm_review: str | None = None
```

## Example Output (fail)

```json
{
  "contract_id": "C001",
  "patch_file": ".harness/patches/C001.diff",
  "passed": false,
  "rule_based_passed": false,
  "violations": [
    {
      "type": "scope_violation",
      "severity": "error",
      "description": "File 'ProductRepository.java' not in contract allowed_files",
      "line_ref": null
    },
    {
      "type": "extra_scope",
      "severity": "warning",
      "description": "Method findByPriceRange() added but not specified in contract spec",
      "line_ref": "added line ~47"
    }
  ],
  "summary": "Patch creates a repository file not in scope. Must be fixed before applying."
}
```

## Example Output (pass)

```json
{
  "contract_id": "C001",
  "passed": true,
  "rule_based_passed": true,
  "violations": [],
  "summary": "Patch follows contract exactly. All 3 allowed files modified. No forbidden patterns."
}
```
