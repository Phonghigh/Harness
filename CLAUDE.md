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

## Karpathy Coding Guidelines

Four principles from Andrej Karpathy's LLM coding observations — enforced on every task.

**1. Think Before Coding** — Surface assumptions before writing any code. If a requirement is ambiguous, name the ambiguity and ask. Never pick silently between interpretations.

**2. Simplicity First** — Minimum code that solves the stated problem. No speculative features, no abstractions for single-use code, no error handling for impossible scenarios. If it could be 50 lines, don't write 200.

**3. Surgical Changes** — Every changed line must trace directly to the user's request. Don't improve adjacent code, don't reformat, don't refactor what isn't broken. Remove only the orphans YOUR changes created.

**4. Goal-Driven Execution** — Define a verifiable success criterion before starting. For each phase item the criterion is the Phase Verification Gate command — the item is not done until that command passes.

> Invoke with `/karpathy-guidelines` or `Skill(karpathy-guidelines)` for the full reference with examples.

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

**Phase 7 — Evaluation & History (complete)**

## Build Progress

### Phase 1 — Workflow Engine
- [x] harness/schemas/task.py
- [x] harness/schemas/decision.py
- [x] harness/schemas/contract.py
- [x] harness/schemas/compliance.py
- [x] harness/config.py
- [x] harness/db.py
- [x] harness/state_machine.py
- [x] harness/services/__init__.py
- [x] harness/services/task_service.py
- [x] harness/services/decision_service.py
- [x] harness/services/contract_service.py
- [x] harness/cli.py (stub version — no LLM calls)
- [x] **PHASE 1 GATE** ← run verification gate before Phase 2

### Phase 2 — LLM Integration
- [x] harness/llm.py
- [x] harness/prompts/interrogator.md
- [x] harness/prompts/contract_builder.md
- [x] harness/prompts/syntax_executor.md
- [x] harness/prompts/compliance_checker.md
- [x] harness/prompts/memory_writer.md
- [x] Wire LLM into task_service (run_interrogate)
- [x] Wire LLM into contract_service (build_contract)
- [x] harness/services/implementation_service.py
- [x] harness/services/validation_service.py
- [x] **PHASE 2 GATE** ← run verification gate before Phase 3

### Phase 3 — Memory & Reuse
- [x] harness/services/memory_service.py
- [x] Memory injection into interrogator prompt
- [x] Conflict detection on `harness approve`
- [x] `harness memory search` and `harness memory delete` commands
- [x] **PHASE 3 GATE**

### Phase 4 — UX Polish
- [x] Decision coverage score in `harness status`
- [x] Interactive `harness answer` (no arg = prompt)
- [x] `harness approve --all`
- [x] `harness report` (markdown export)
- [x] `harness config set <key> <value>`
- [x] **PHASE 4 GATE**

### Phase 5 — MCP Server
- [x] harness/server.py (FastMCP, 11 tools, 4 resources)
- [x] harness/prompts/conflict_detector.md
- [x] `harness serve` command in cli.py
- [x] pyproject.toml: mcp dependency + harness-mcp entry point
- [x] **PHASE 5 GATE**

### Phase 6 — Advanced Compliance + Traceability
- [x] harness/schemas/contract.py: `decision_ids` field
- [x] harness/schemas/compliance.py: `error_count`, `warning_count` fields
- [x] harness/db.py: `decision_ids_json` column + migration
- [x] harness/services/conflict_service.py (LLM + fast fallback)
- [x] harness/services/decision_service.py: uses conflict_service
- [x] harness/services/contract_service.py: populates decision_ids
- [x] harness/services/validation_service.py: populates error/warning counts
- [x] harness/cli.py: inline diff preview + colored violation output
- [x] **PHASE 6 GATE**

### Phase 7 — Evaluation & History
- [x] harness/schemas/evaluation.py
- [x] harness/services/evaluation_service.py
- [x] harness/db.py: evaluations table, list_tasks, memory tracking columns
- [x] harness/services/memory_service.py: source_task_id + applied_count tracking
- [x] harness/cli.py: `harness history`, `harness eval`, `memory list` Applied column
- [x] tests/ (56 tests — state_machine, decision, contract, validation, memory)
- [x] **PHASE 7 GATE**

### Phase 8 — Land Uncommitted Changes

- [x] Verify pytest green + no `import typer` in services
- [x] Commit: cli.py run, auto_answer_decisions, decision_answerer.md, compliance_checker.md, contract two-step parse
- [x] **PHASE 8 GATE**

### Phase 9 — Memory Category Column (already implemented)

- [ ] Verify gate command passes (category column, upsert, list_memory, conflict_service)
- [ ] **PHASE 9 GATE**

### Phase 10 — Agent Runtime

- [ ] harness/runtime.py (PauseReason, RuntimeResult, run_until_pause)
- [ ] implementation_service.py: reimplement()
- [ ] state_machine.py: COMMAND_REQUIRES["reimplement"]
- [ ] cli.py: slim run command + _render_runtime_result()
- [ ] tests/test_runtime.py (4 tests)
- [ ] **PHASE 10 GATE**

### Phase 11 — Contract and Patch Lifecycle Gates

- [ ] schemas/task.py: WAITING_FOR_CONTRACT_APPROVAL, WAITING_FOR_PATCH_APPROVAL
- [ ] state_machine.py: new transitions + COMMAND_REQUIRES entries
- [ ] contract_service.py: build_contract → WAITING_FOR_CONTRACT_APPROVAL, approve_contract, reject_contract
- [ ] implementation_service.py: implement → WAITING_FOR_PATCH_APPROVAL, approve_patch, reject_patch
- [ ] db.py: update_patch_status()
- [ ] cli.py: contract-approve, contract-reject, apply, patch-reject
- [ ] runtime.py: pause after contract build + implement, auto_approve flag
- [ ] server.py: 4 new MCP tools
- [ ] **PHASE 11 GATE**

### Phase 12 — Event Log and harness trace

- [ ] db.py: events table DDL + log_event, get_events, new_event_id
- [ ] state_machine.py: emit state_transition events in transition()
- [ ] runtime.py: _timed_service_call wrapper
- [ ] cli.py: harness trace command
- [ ] **PHASE 12 GATE**

### Phase 13 — LLM Robustness

- [ ] llm.py: retry loop + _is_retriable, _call split, token tracking
- [ ] config.py: max_tokens, llm_retries fields
- [ ] cli.py: config set supports max_tokens, llm_retries
- [ ] tests/test_llm.py (4 tests)
- [ ] **PHASE 13 GATE**

### Phase 14 — Policy Engine (optional)

- [ ] harness/policy.py (RiskLevel, PolicyDecision, DECISION_GATES, check_decision_gate, check_patch_risk)
- [ ] runtime.py: integrate check_decision_gate before auto-approve
- [ ] **PHASE 14 GATE**

### Phase 15 — Claude Code Syntax Executor Integration

Full spec: `plans/phase15_claude_code_integration.md`

- [ ] harness/config.py: `use_claude_code: bool = True`, `claude_code_timeout: int = 300`
- [ ] harness/services/claude_executor.py: 5 functions (is_claude_available, build_impl_prompt, run_claude_implement, capture_diff_staged, reset_allowed_files)
- [ ] harness/services/implementation_service.py: implement() + reimplement() dispatch to Claude Code or LLM
- [ ] harness/runtime.py: pass `config=config` to implement() and reimplement()
- [ ] harness/cli.py: config-set handles use_claude_code/claude_code_timeout, implement shows mode, apply shows mode-aware message
- [ ] harness/server.py: harness_implement tool passes config=config
- [ ] harness/app.py: mode badge, mode-aware apply button, config toggles
- [ ] tests/test_claude_executor.py: 13 tests
- [ ] **PHASE 15 GATE**

```bash
python -c "from harness.services.claude_executor import is_claude_available; print('claude:', is_claude_available())"
python -c "from harness.config import HarnessConfig; c = HarnessConfig(project_name='x', llm_provider='anthropic', llm_model='m'); assert c.use_claude_code == True; print('config OK')"
pytest tests/test_claude_executor.py -v
pytest tests/ -q
harness config set use_claude_code true
harness config set claude_code_timeout 120
```

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
/loop Continue building the Harness project. Read CLAUDE.md Build Progress, find the first unchecked [ ] phase item, implement it per the plan at /home/fionn/.claude/plans/harness-complete-build-hashed-garden.md, run its GATE command (must pass green), mark [x] in CLAUDE.md, then continue to the next unchecked item. Never skip the GATE. Never auto-apply patches. Never commit without running pytest first.
```

To implement Phase 15 (Claude Code integration) specifically:

```
/loop Implement Phase 15 — Claude Code Syntax Executor Integration in Harness.

PLAN FILE: plans/phase15_claude_code_integration.md
CHECKLIST SECTION: "Build Checklist" (the - [ ] items)

For each unchecked [ ] item:
1. Read the corresponding Phase section in plans/phase15_claude_code_integration.md for exact specs
2. Implement exactly what the spec says — no more, no less
3. Run the Phase Gate command from the plan — it MUST pass green before continuing
4. Mark the item [x] in plans/phase15_claude_code_integration.md
5. Also mark the matching item [x] in CLAUDE.md under "Phase 15"
6. Run pytest tests/ -q — must be green after every phase
7. Move to the next unchecked item

Rules:
- Never skip a Gate
- Never commit without pytest passing
- Never implement beyond what the phase spec says
- If a Gate fails, fix it before moving on
- After all 9 items are checked, print "Phase 15 COMPLETE"
```

Full loop instructions: `knowledge/AGENT_LOOP.md`
Detailed specs per phase: `/home/fionn/.claude/plans/harness-complete-build-hashed-garden.md`
Phase 15 spec: `plans/phase15_claude_code_integration.md`
Reference docs: `knowledge/`
