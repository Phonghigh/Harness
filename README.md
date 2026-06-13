# Architect Harness

**A decision-first AI coding system. Humans own all architecture decisions. AI converts approved contracts into syntax — never requirements directly into code.**

```
Ask → Decide → Contract → Syntax → Check → Remember
```

---

## What Is This?

Most AI coding tools take a requirement and immediately generate code. Harness refuses to do that.

Instead, every feature request is first decomposed into **5–10 explicit architecture decisions** (data model, API contract, security, persistence, etc.). A human reviews and approves each decision. Only then does the AI generate a precise implementation contract — and only then does it write code.

The result: no surprises. Every line of generated code is traceable to a human-approved decision.

---

## Core Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  1. ASK        harness start "Add user login with JWT"          │
│       │                                                         │
│  2. DECIDE     harness interrogate   → LLM generates 5-10       │
│       │        harness decisions         architecture questions  │
│       │        harness answer D001 "JWT RS256"                  │
│       │        harness approve --all                            │
│       │                                                         │
│  3. CONTRACT   harness contract      → LLM builds spec:         │
│       │        harness contract-approve  files, constraints,     │
│       │                                  acceptance criteria     │
│       │                                                         │
│  4. SYNTAX     harness implement     → Claude Code or LLM       │
│       │        harness apply             generates patch file    │
│       │                                                         │
│  5. CHECK      harness check         → Rule-based + LLM         │
│       │                                  compliance review       │
│       │        harness validate      → Run your test suite      │
│       │                                                         │
│  6. REMEMBER   harness remember      → LLM extracts lessons,    │
│                                          stores in memory DB     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

### Decision Engine
- Interrogates any requirement into **5–10 typed architecture decisions** across 15 categories (data_model, api_contract, security_permission, persistence_transaction, etc.)
- Each decision has options, an LLM recommendation, and a human-selected answer
- `harness approve --all` for auto-approve with conflict detection
- **Policy gates**: `security_permission`, `migration_compatibility`, `architecture_pattern` always require human approval regardless of automation level
- Conflict detection: LLM-based semantic check + fast antonym-pair fallback

### Contract System
- Approved decisions compile into a typed implementation contract: allowed files, forbidden patterns, acceptance criteria, constraints
- Contracts are human-reviewable before implementation begins
- Decision IDs are embedded in every contract for full traceability
- `contract-approve` / `contract-reject` cycle — reject sends back to decisions for rebuild

### Implementation — Two Modes
| Mode | How | When |
|------|-----|------|
| **Claude Code** (default) | Shells out to `claude` CLI with the contract as prompt, captures staged git diff | When `claude` is in PATH |
| **LLM Syntax Executor** | Sends contract + file contents to LLM, receives unified diff | Fallback when Claude Code unavailable |

### Compliance Checking
- **Rule-based**: scope violations (files not in `allowed_files`), forbidden pattern matching, missing spec files
- **LLM semantic**: reads contract + patch, flags violations missed by rules
- Error violations block progress; warnings are informational
- Re-implementation loop: fail → reimplement → check again (max 3 retries)
- Patch approve / reject cycle before compliance runs

### Memory System — Layered Learning
The memory system applies Claude Code's layered memory architecture to an AI agent:

**6 memory types with distinct lifecycles:**

| Type | Purpose | Written when |
|------|---------|-------------|
| `project_standard` | Stable architectural decisions | Task DONE (LLM) |
| `architecture_rule` | Hard constraints | Task DONE (LLM) |
| `feedback` | Human override rationales | Human overrides recommendation (instant) |
| `compliance_pattern` | Recurring violation fixes | Compliance fails (instant) |
| `interrogation_pattern` | Which categories matter for requirement types | Evaluation detects missing categories (instant) |
| `lesson` | Soft learnings | Task DONE (LLM) + first-pass compliance success |

**Memory is written at 5 lifecycle points** (not just at DONE):
```
answer_decision()     → feedback memory if human overrides LLM
approve_decisions()   → feedback memory if conflict detected but approved
check_compliance()    → compliance_pattern per error violation
write_memory()        → 2–6 typed lessons via LLM at DONE
compute_evaluation()  → interrogation_pattern, compliance_pattern, lesson from metrics
```

**Category-scoped injection**: when auto-answering a `data_model` decision, only `data_model` memories + permanent anchors (`project_standard`, `architecture_rule`) are injected — not testing memories, not security memories.

### Runtime Automation
- `harness run "requirement"` — fully autonomous end-to-end with pause points
- Pause reasons: HUMAN_DECISIONS_REQUIRED, CONTRACT_APPROVAL_REQUIRED, PATCH_APPROVAL_REQUIRED, COMPLIANCE_FAILED, DONE
- Policy engine gates auto-approval by decision category
- `--auto-approve` flag bypasses human gates (for scripted pipelines)

### MCP Server
Full workflow exposed as an MCP server for Claude Code / Cursor integration:

**15 tools**: `harness_create_task`, `harness_interrogate`, `harness_list_decisions`, `harness_answer_decision`, `harness_approve_decisions`, `harness_build_contract`, `harness_approve_contract`, `harness_reject_contract`, `harness_implement`, `harness_approve_patch`, `harness_reject_patch`, `harness_check_compliance`, `harness_validate`, `harness_write_memory`, `harness_get_status`

**4 resources**: `harness://active_task`, `harness://decisions/{task_id}`, `harness://contract/{task_id}`, `harness://memories`

### Event Log & Tracing
Every state transition, LLM call, and tool invocation is logged to an `events` table.
`harness trace` shows the full timeline of any task with duration per step.

### Evaluation & History
After every task, `harness eval` computes:
- Decision coverage: which of the 15 categories were addressed
- Compliance: retries, first-pass rate, final violation counts
- Memory: how many entries this task generated
- Cycle time: total seconds from start to DONE

`harness history` shows the last 50 tasks with status and timing.

### Streamlit Dashboard
`harness ui` launches a local web dashboard with 6 pages:
- Start Task, Decisions (answer + approve), Contract (review + approve), Patch (generate + review), History, Memory (search + delete)

---

## CLI Reference

```
harness init --provider anthropic --model claude-sonnet-4-6
harness start "requirement"
harness run "requirement"          # fully automated

# Decision cycle
harness status
harness interrogate
harness decisions
harness answer D001 "JWT RS256"
harness approve D001
harness approve --all

# Contract cycle
harness contract
harness contract-approve
harness contract-reject

# Implementation cycle
harness implement C001
harness apply                      # approve patch
harness patch-reject               # reject patch → back to CONTRACT_READY
harness check C001
harness validate

# Completion
harness remember
harness eval
harness history
harness trace

# Memory
harness memory list [--type feedback] [--scope myproject]
harness memory search "JWT"
harness memory summary [--write]   # MEMORY.md-style index
harness memory delete M1A2B3

# Config
harness config set use_claude_code true
harness config set claude_code_timeout 120
harness config set max_tokens 4096
harness config set llm_retries 3

# Server & UI
harness serve                      # MCP server (stdio)
harness ui                         # Streamlit dashboard
harness report                     # Markdown export of current task
```

---

## Architecture

```
harness/
├── schemas/           ← no external deps; pure data models
│   ├── task.py        TaskStatus (10 states), Task
│   ├── decision.py    Decision, DECISION_CATEGORIES (15), MEMORY_TYPES (6)
│   ├── contract.py    Contract, ContractSpec, FileSpec
│   ├── compliance.py  ComplianceReport, Violation, ViolationType
│   └── evaluation.py  TaskEvaluation, DecisionCoverageMetric, ComplianceMetric
│
├── config.py          ← HarnessConfig (pydantic-settings), find_harness_root
├── db.py              ← SQLite, 8 tables, all CRUD, idempotent migrations
├── state_machine.py   ← TRANSITIONS dict, COMMAND_REQUIRES dict, transition()
├── llm.py             ← AnthropicAdapter / OpenAIAdapter, retry logic, token tracking
├── policy.py          ← RiskLevel, DECISION_GATES, check_decision_gate
├── runtime.py         ← run_until_pause(), PauseReason, RuntimeResult
│
├── services/
│   ├── task_service.py          create_task, run_interrogate
│   ├── decision_service.py      answer_decision, approve_decisions, auto_answer
│   ├── contract_service.py      build_contract, approve_contract, reject_contract
│   ├── implementation_service.py implement, reimplement, approve_patch, reject_patch
│   ├── validation_service.py    check_compliance
│   ├── memory_service.py        inject_project_memory, write_memory, write_event_memory
│   ├── conflict_service.py      detect_conflicts_llm, detect_conflicts_fast
│   ├── evaluation_service.py    compute_task_evaluation
│   ├── scanner_service.py       build_codebase_context (file tree for LLM context)
│   └── claude_executor.py       is_claude_available, run_claude_implement, capture_diff_staged
│
├── prompts/           ← all LLM system prompts as .md files
│   ├── interrogator.md
│   ├── decision_answerer.md
│   ├── conflict_detector.md
│   ├── contract_builder.md
│   ├── syntax_executor.md
│   ├── compliance_checker.md
│   └── memory_writer.md
│
├── cli.py             ← typer app; imports only from services, never vice versa
├── server.py          ← FastMCP; 15 tools + 4 resources
└── app.py             ← Streamlit dashboard
```

**Dependency order** (strict — lower layers never import from upper):
```
schemas → config → db → state_machine → llm → services → cli/server/app
```

---

## Database Schema

```
tasks              — id, title, raw_requirement, status, timestamps
decisions          — id, task_id, category, question, options_json,
                     recommendation, selected_answer, rationale, confidence,
                     status, timestamps
contracts          — id, task_id, scope, allowed_files_json, forbidden_json,
                     spec_json, status, decision_ids_json, created_at
patches            — id, contract_id, diff_text, status, created_at
compliance_reports — id, contract_id, patch_id, passed, violations_json,
                     summary, created_at
memory             — id, type, scope, key, value_json, category,
                     source_task_id, applied_count, last_applied_at, timestamps
evaluations        — id, task_id, contract_id, metrics_json, created_at
events             — id, task_id, event_type, from_state, to_state,
                     tool_name, prompt_name, duration_ms, metadata_json, created_at
```

Migrations are idempotent — `db.initialize()` is safe to run on existing databases.

---

## State Machine

```
INTAKE
  └─[interrogate]──→ INTERROGATING
                          └─[auto]──→ WAITING_FOR_DECISIONS
                                          └─[approve]──→ DECISIONS_APPROVED
                                                              └─[contract]──→ WAITING_FOR_CONTRACT_APPROVAL
                                                                                  ├─[contract-approve]──→ CONTRACT_READY
                                                                                  └─[contract-reject]───→ DECISIONS_APPROVED
CONTRACT_READY
  └─[implement]──→ WAITING_FOR_PATCH_APPROVAL
                        ├─[apply]────────────→ IMPLEMENTING
                        └─[patch-reject]─────→ CONTRACT_READY
IMPLEMENTING
  └─[check]──→ CHECKING_COMPLIANCE
                    ├─[pass]──→ VALIDATING
                    │               ├─[pass]──→ DONE
                    │               └─[fail]──→ IMPLEMENTING
                    └─[fail]──→ IMPLEMENTING
```

Every transition emits an event record to the `events` table.

---

## Task Lifecycle Guarantees

| Rule | Enforcement |
|------|-------------|
| No LLM call before correct state | `assert_command_allowed()` raises `WrongStateError` |
| No code without approved contract | State machine blocks `implement` until `CONTRACT_READY` |
| No patch applied without compliance | `apply` command only available after `check` passes |
| Patch files never auto-applied | `harness apply` is always an explicit human action |
| One active task at a time | `create_task()` checks for existing active task |
| Memory written only after DONE | `assert_command_allowed("remember", ...)` |
| Services never import from CLI | Enforced by architecture; CLI is the only leaf |

---

## Build Progress

All 15 phases complete. See [.claude/rules/build-history.md](.claude/rules/build-history.md) for the full checklist.

| Phase | Feature |
|-------|---------|
| 1 | Workflow engine — state machine, DB, CLI stub |
| 2 | LLM integration — interrogator, contract builder, syntax executor |
| 3 | Memory & reuse — memory table, injection, conflict detection |
| 4 | UX polish — coverage score, interactive answer, `--all` approve, report export |
| 5 | MCP server — 11 tools, 4 resources, FastMCP |
| 6 | Advanced compliance — decision traceability, error/warning counts, inline diff |
| 7 | Evaluation & history — metrics, `harness history`, `harness eval` |
| 8 | Land uncommitted changes — pytest green, no typer in services |
| 9 | Memory category column — upsert, category filter, conflict scoping |
| 10 | Agent runtime — `run_until_pause()`, reimplement loop |
| 11 | Contract & patch lifecycle gates — approve/reject cycles, `apply`, `patch-reject` |
| 12 | Event log & trace — events table, `harness trace` |
| 13 | LLM robustness — retry loop, token tracking, configurable retries |
| 14 | Policy engine — RiskLevel, DECISION_GATES, auto-approve gating |
| 15 | Claude Code integration — `claude` CLI executor, staged diff capture, mode badge |
| 16 | Claude memory principles — MEMORY_TYPES taxonomy, feedback memory, category-scoped injection, incremental event writes, evaluation→memory pipeline, `harness memory summary` |

---

## Tests

```bash
pytest tests/ -q        # 90 tests, ~0.8s
```

| File | Coverage |
|------|---------|
| `test_state_machine.py` | All transitions, invalid transition errors |
| `test_decision.py` | Decision creation, approval, conflict detection |
| `test_contract.py` | Contract building, decision_ids population |
| `test_validation.py` | Compliance report, error/warning counts |
| `test_memory.py` | Memory upsert, category, applied_count, source_task_id |
| `test_runtime.py` | PauseReason, RuntimeResult, run_until_pause |
| `test_llm.py` | Retry loop, _is_retriable, token tracking |
| `test_claude_executor.py` | is_claude_available, build_impl_prompt, capture_diff_staged |

---

## Installation

```bash
git clone <repo>
cd Harness
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Set API key
export ANTHROPIC_API_KEY=sk-...
# or: export HARNESS_PROVIDER=openai && export OPENAI_API_KEY=sk-...

# Initialize a project
cd your-project
harness init --provider anthropic --model claude-sonnet-4-6
```

### MCP Server Setup (Claude Code)

Add to `.claude/settings.json`:
```json
{
  "mcpServers": {
    "harness": {
      "command": "harness-mcp",
      "transport": "stdio"
    }
  }
}
```

---

## Knowledge Base

Detailed design documentation in [knowledge/](knowledge/):

| File | Contents |
|------|---------|
| `01_product_vision.md` | Core principle and design philosophy |
| `02_core_loop.md` | The 6-step workflow in detail |
| `03_decision_taxonomy.md` | All 15 decision categories with examples |
| `04_state_machine.md` | State transition rules and invariants |
| `05_db_schema.md` | Full database schema with field descriptions |
| `06_architecture.md` | Module dependency graph and layering rules |
| `07_prompt_patterns.md` | LLM prompt design patterns used throughout |
| `08_cli_reference.md` | Full CLI command reference |
| `09_compliance_rules.md` | Compliance check logic and violation types |
| `10_memory_system.md` | Memory architecture, types, injection, conflict detection |
| `AGENT_LOOP.md` | Instructions for autonomous agent continuation |
