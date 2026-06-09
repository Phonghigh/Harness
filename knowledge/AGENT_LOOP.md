# Agent Loop — Autonomous Build Continuation

## How to Invoke

Run this in Claude Code to autonomously continue building the project:

```
/loop Continue building the Harness project. Read CLAUDE.md, find the first unchecked [ ] item in Build Progress, implement it per the master plan and knowledge/ docs, run its verification command, mark [x] in CLAUDE.md, continue to next item.
```

Or for a single step (without looping):
```
Continue building the Harness project. Read CLAUDE.md in /home/fionn/Documents/Dev/Harness, find the first unchecked [ ] item in Build Progress, implement it, verify it, mark it [x].
```

---

## Full Loop Instructions

### On Every Iteration

1. **Read `CLAUDE.md`** — find "Current Phase" and "Build Progress"
2. **Find first unchecked item** — the first `- [ ]` in the current phase
3. **Look up the spec** — read the corresponding section in:
   - Master plan: `/home/fionn/.claude/plans/ch-nh-x-c-b-n-ang-eventual-stallman.md`
   - Knowledge docs: `knowledge/` (see index in `knowledge/README.md`)
4. **Implement** the task
5. **Verify** using the command from `CLAUDE.md ## Task Verification Commands`
6. **If verification passes**: mark `[x]` in `CLAUDE.md` Build Progress
7. **If verification fails**: fix, re-verify, then mark `[x]`
8. **If all items in phase are `[x]`**: run the Phase Verification Gate
   - Gate passes → update "Current Phase" in CLAUDE.md to next phase
   - Gate fails → do NOT advance; report what failed and stop
9. **Continue** to next unchecked item if context allows, else stop and report

---

## Non-Negotiable Loop Rules

- Never mark `[x]` before the verification command passes
- Never skip a task, even if it seems trivial
- Never advance phase until the Phase Verification Gate passes end-to-end
- Always follow the 10 rules in `CLAUDE.md ## Non-Negotiable Rules`
- Services may never import from `cli.py`
- Schemas are frozen once a layer above them is implemented — discuss before changing
- Prompt templates are locked after Phase 2 — changing one is a breaking change

---

## Per-Task Reference

### Phase 1 Tasks

#### schemas/compliance.py
**Spec:** `knowledge/09_compliance_rules.md` + plan Phase 1.1

```python
# harness/schemas/compliance.py
from enum import StrEnum
from pydantic import BaseModel

class ViolationType(StrEnum):
    SCOPE_VIOLATION = "scope_violation"
    FORBIDDEN_PATTERN = "forbidden_pattern"
    MISSING_SPEC = "missing_spec"
    EXTRA_SCOPE = "extra_scope"

class Violation(BaseModel):
    type: ViolationType
    severity: str   # "error" | "warning"
    description: str
    line_ref: str | None = None

class ComplianceReport(BaseModel):
    contract_id: str
    patch_file: str
    passed: bool
    violations: list[Violation]
    summary: str
    rule_based_passed: bool
    llm_review: str | None = None
```

Verify:
```bash
python -c "from harness.schemas.compliance import ComplianceReport, Violation; print('OK')"
```

---

#### harness/config.py
**Spec:** plan Phase 1.2, `knowledge/06_architecture.md`

Key elements:
- `HarnessConfig(BaseModel)`: project_name, llm_provider (str, no default), llm_model (str), validate_commands: list[str] = []
- `EnvSettings(BaseSettings)`: reads ANTHROPIC_API_KEY, OPENAI_API_KEY, HARNESS_PROVIDER from env
- `find_harness_root(start)`: walks up dirs looking for `.harness/config.json`
- `load_config()`: returns (harness_dir, config), raises typer.BadParameter if not initialized
- `save_config(harness_dir, config)`: writes JSON

Verify:
```bash
python -c "from harness.config import find_harness_root, HarnessConfig, EnvSettings; print('OK')"
```

---

#### harness/db.py
**Spec:** plan Phase 1.3, `knowledge/05_db_schema.md`

6 tables: tasks, decisions, contracts, patches, compliance_reports, memory.
Use `contextmanager` pattern from `knowledge/07_prompt_patterns.md` SK-5.
ID generation: T-prefix (uuid hex), D-prefix (sequential scoped), C-prefix (sequential global).

Verify:
```bash
python -c "
from harness.db import Database
from pathlib import Path
import tempfile
with tempfile.TemporaryDirectory() as d:
    db = Database(Path(d) / 'test.db')
    db.initialize()
    tid = 'T001'
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    db.create_task({'id': tid, 'title': 'Test', 'raw_requirement': 'Test req', 'status': 'INTAKE', 'created_at': now, 'updated_at': now})
    task = db.get_active_task()
    assert task['id'] == tid
    print('DB OK')
"
```

---

#### harness/state_machine.py
**Spec:** plan Phase 1.4, `knowledge/04_state_machine.md`

Implement TRANSITIONS dict and COMMAND_REQUIRES dict exactly as in the docs.
Three functions: `validate_transition`, `assert_command_allowed`, `transition`.

Verify:
```bash
python -c "
from harness.state_machine import validate_transition, assert_command_allowed, InvalidTransitionError, WrongStateError
from harness.schemas.task import TaskStatus
validate_transition(TaskStatus.INTAKE, TaskStatus.INTERROGATING)
try:
    validate_transition(TaskStatus.INTAKE, TaskStatus.IMPLEMENTING)
    print('FAIL — should have raised')
except InvalidTransitionError as e:
    print('State machine OK:', str(e)[:60])
"
```

---

#### harness/services/ (task + decision + contract)
**Spec:** plan Phase 1.5

Create `services/__init__.py` (empty) first.

`task_service.py`: `create_task()`, `get_active_task_or_exit()`
`decision_service.py`: `list_decisions()`, `answer_decision()`, `approve_decisions()`
`contract_service.py`: `build_contract()` — stub version returns hardcoded contract data

Use SK-2 (State Gate Pattern) in every function that changes state.

Verify:
```bash
python -c "from harness.services.task_service import create_task, get_active_task_or_exit; print('task_service OK')"
python -c "from harness.services.decision_service import list_decisions, answer_decision, approve_decisions; print('decision_service OK')"
python -c "from harness.services.contract_service import build_contract; print('contract_service OK')"
```

---

#### harness/cli.py (stub version)
**Spec:** plan Phase 1.6, `knowledge/08_cli_reference.md`

All 13 commands wired up. LLM calls replaced with `typer.echo("[STUB] ...")`.
`get_context()` helper: calls `load_config()`, opens Database, (stub: no LLM adapter yet).

Verify:
```bash
harness --help
harness init --help
harness start --help
```

---

### Phase 1 Gate

Run ALL of these. Every command must complete without error.

```bash
cd /tmp && mkdir test-harness && cd test-harness
harness init --provider anthropic --model claude-sonnet-4-6
harness start "Add product CRUD"
harness status
harness interrogate       # [STUB] decisions
harness decisions
harness answer D001 "Use DTO"
harness approve D001
# answer + approve all remaining stub decisions
harness contract
harness implement C001
harness check C001
harness validate
harness remember
harness memory list
```

All commands must work with NO ANTHROPIC_API_KEY set.

---

### Phase 2 Tasks (after Phase 1 Gate passes)

When Phase 1 is complete, update `CLAUDE.md`:
1. Change "Current Phase" to "Phase 2 — LLM Integration"
2. Continue with the Phase 2 checklist

Phase 2 starts with `harness/llm.py` (plan Phase 2.1).

---

## Reporting Format

At the end of each iteration, report:

```
Completed: harness/schemas/compliance.py
Verified: ✓ (import OK)
CLAUDE.md: updated (compliance.py checked off)

Next: harness/config.py
```

If gate fails:
```
Phase 1 Gate: FAILED
Failing command: harness contract
Error: [error output]
Phase NOT advanced. Fix needed before proceeding.
```
