# Architect-Driven Coding Harness — Agent Context

## What This Is

A decision-first AI coding system. Humans own all architecture decisions. AI converts approved contracts into syntax — never requirements directly into code.

Core loop (IMMUTABLE):
```
Ask → Decide → Contract → Syntax → Check → Remember
```

## Non-Negotiable Rules (read before every task)

1. State machine is the gatekeeper — commands that skip states must **raise**, not warn
2. No LLM call before state allows it: interrogate=INTAKE, contract=DECISIONS_APPROVED, implement=CONTRACT_READY
3. Syntax Executor reads contract JSON only — never raw requirement
4. Compliance check runs before any `git apply`
5. Patch files go to `.harness/patches/` — never auto-applied
6. One active task at a time (MVP)
7. Memory written only after DONE
8. Prompt templates in `harness/prompts/*.md` — never hardcoded in Python
9. All LLM output parsed via `model_validate_json()` — never bare `json.loads()`
10. Services never import from `cli.py` — only CLI imports services

## Architecture (build strictly in this order)

```
schemas/         ← no deps (done ✓)
    task.py      ✓
    decision.py  ✓
    contract.py  ✓
    compliance.py  ← next
        ↓
config.py        ← pathlib + pydantic-settings
        ↓
db.py            ← sqlite3 + schemas
        ↓
state_machine.py ← schemas/task.py only
        ↓
llm.py           ← anthropic/openai SDK + prompts/*.md
        ↓
services/        ← db + state_machine + llm + schemas
        ↓
cli.py           ← all services + rich
```

## Tool Usage

| Situation | Tool |
|-----------|------|
| After writing any `.py` file | `python -c "from harness.X import Y; print('OK')"` |
| After completing a phase | `/code-review` on changed files |
| Before marking phase gate | run Phase Verification Gate commands below |
| Service is complex | `/simplify` after first pass |
| Adding a new permission | `/update-config` skill |
| LLM prompt needs testing | Bash with real API key + inline Python |

## Current Phase

**Phase 1 — Workflow Engine (no LLM)**

## Build Progress

### Phase 1 — Workflow Engine
- [x] harness/schemas/task.py
- [x] harness/schemas/decision.py
- [x] harness/schemas/contract.py
- [ ] harness/schemas/compliance.py
- [ ] harness/config.py
- [ ] harness/db.py
- [ ] harness/state_machine.py
- [ ] harness/services/__init__.py
- [ ] harness/services/task_service.py
- [ ] harness/services/decision_service.py
- [ ] harness/services/contract_service.py
- [ ] harness/cli.py (stub version — no LLM calls)
- [ ] **PHASE 1 GATE** ← run verification gate before Phase 2

### Phase 2 — LLM Integration
- [ ] harness/llm.py
- [ ] harness/prompts/interrogator.md
- [ ] harness/prompts/contract_builder.md
- [ ] harness/prompts/syntax_executor.md
- [ ] harness/prompts/compliance_checker.md
- [ ] harness/prompts/memory_writer.md
- [ ] Wire LLM into task_service (run_interrogate)
- [ ] Wire LLM into contract_service (build_contract)
- [ ] harness/services/implementation_service.py
- [ ] harness/services/validation_service.py
- [ ] **PHASE 2 GATE** ← run verification gate before Phase 3

### Phase 3 — Memory & Reuse
- [ ] harness/services/memory_service.py
- [ ] Memory injection into interrogator prompt
- [ ] Conflict detection on `harness approve`
- [ ] `harness memory search` and `harness memory delete` commands
- [ ] **PHASE 3 GATE**

### Phase 4 — UX Polish
- [ ] Decision coverage score in `harness status`
- [ ] Interactive `harness answer` (no arg = prompt)
- [ ] `harness approve --all`
- [ ] `harness report` (markdown export)
- [ ] `harness config set <key> <value>`
- [ ] **PHASE 4 GATE**

## Phase Verification Gates

### Phase 1 Gate
All commands must work with NO API KEY set (stubs only).

```bash
harness init --provider anthropic --model claude-sonnet-4-6
harness start "Add product CRUD"
harness status
harness interrogate         # → [STUB] decisions generated
harness decisions
harness answer D001 "Use DTO"
harness approve D001
harness contract            # → [STUB] C001 created
harness implement C001      # → patch written (stub)
harness check C001          # → [STUB] PASS
harness validate            # → DONE
harness remember            # → [STUB] memories
harness memory list
```

### Phase 2 Gate
Requires real API key.

```bash
export HARNESS_PROVIDER=anthropic
export ANTHROPIC_API_KEY=<key>
harness start "Add user login with JWT"
harness interrogate         # → real 6-10 decisions
harness answer D001 "JWT RS256"
# ... answer remaining
harness approve --all
harness contract            # → real contract JSON
harness implement C001      # → real .diff file in .harness/patches/
harness check C001          # → rule-based + LLM compliance report
harness validate
harness remember
harness memory list         # → real memory entries
```

## Task Verification Commands

```bash
# schemas/compliance.py
python -c "from harness.schemas.compliance import ComplianceReport, Violation; print('OK')"

# config.py
python -c "from harness.config import find_harness_root, HarnessConfig; print('OK')"

# db.py
python -c "
from harness.db import Database
from pathlib import Path, tempfile
import tempfile
with tempfile.TemporaryDirectory() as d:
    db = Database(Path(d) / 'test.db')
    db.initialize()
    print('DB OK')
"

# state_machine.py
python -c "
from harness.state_machine import validate_transition, assert_command_allowed, InvalidTransitionError
from harness.schemas.task import TaskStatus
validate_transition(TaskStatus.INTAKE, TaskStatus.INTERROGATING)
try:
    validate_transition(TaskStatus.INTAKE, TaskStatus.IMPLEMENTING)
    print('FAIL')
except InvalidTransitionError as e:
    print('State machine OK:', e)
"

# services
python -c "from harness.services.task_service import create_task; print('task_service OK')"
python -c "from harness.services.decision_service import list_decisions; print('decision_service OK')"
python -c "from harness.services.contract_service import build_contract; print('contract_service OK')"

# cli
harness --help
```

## Agent Continuation

To resume building autonomously:
```
/loop Continue building the Harness project. Read CLAUDE.md, find the first unchecked [ ] item in Build Progress, implement it per the plan at /home/fionn/.claude/plans/ch-nh-x-c-b-n-ang-eventual-stallman.md and knowledge/ docs, run its verification command, mark [x], continue to next item.
```

Full loop instructions: `knowledge/AGENT_LOOP.md`
Detailed specs per phase: `/home/fionn/.claude/plans/ch-nh-x-c-b-n-ang-eventual-stallman.md`
Reference docs: `knowledge/`
