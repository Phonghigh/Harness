# Build History — All Phases Complete Through Phase 15

All 15 phases are complete. This file is a reference archive of the build checklist.

## Phase 1 — Workflow Engine
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
- [x] **PHASE 1 GATE**

## Phase 2 — LLM Integration
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
- [x] **PHASE 2 GATE**

## Phase 3 — Memory & Reuse
- [x] harness/services/memory_service.py
- [x] Memory injection into interrogator prompt
- [x] Conflict detection on `harness approve`
- [x] `harness memory search` and `harness memory delete` commands
- [x] **PHASE 3 GATE**

## Phase 4 — UX Polish
- [x] Decision coverage score in `harness status`
- [x] Interactive `harness answer` (no arg = prompt)
- [x] `harness approve --all`
- [x] `harness report` (markdown export)
- [x] `harness config set <key> <value>`
- [x] **PHASE 4 GATE**

## Phase 5 — MCP Server
- [x] harness/server.py (FastMCP, 11 tools, 4 resources)
- [x] harness/prompts/conflict_detector.md
- [x] `harness serve` command in cli.py
- [x] pyproject.toml: mcp dependency + harness-mcp entry point
- [x] **PHASE 5 GATE**

## Phase 6 — Advanced Compliance + Traceability
- [x] harness/schemas/contract.py: `decision_ids` field
- [x] harness/schemas/compliance.py: `error_count`, `warning_count` fields
- [x] harness/db.py: `decision_ids_json` column + migration
- [x] harness/services/conflict_service.py (LLM + fast fallback)
- [x] harness/services/decision_service.py: uses conflict_service
- [x] harness/services/contract_service.py: populates decision_ids
- [x] harness/services/validation_service.py: populates error/warning counts
- [x] harness/cli.py: inline diff preview + colored violation output
- [x] **PHASE 6 GATE**

## Phase 7 — Evaluation & History
- [x] harness/schemas/evaluation.py
- [x] harness/services/evaluation_service.py
- [x] harness/db.py: evaluations table, list_tasks, memory tracking columns
- [x] harness/services/memory_service.py: source_task_id + applied_count tracking
- [x] harness/cli.py: `harness history`, `harness eval`, `memory list` Applied column
- [x] tests/ (56 tests — state_machine, decision, contract, validation, memory)
- [x] **PHASE 7 GATE**

## Phase 8 — Land Uncommitted Changes
- [x] Verify pytest green + no `import typer` in services
- [x] Commit: cli.py run, auto_answer_decisions, decision_answerer.md, compliance_checker.md, contract two-step parse
- [x] **PHASE 8 GATE**

## Phase 9 — Memory Category Column (already implemented)
- [x] Verify gate command passes (category column, upsert, list_memory, conflict_service)
- [x] **PHASE 9 GATE**

## Phase 10 — Agent Runtime
- [x] harness/runtime.py (PauseReason, RuntimeResult, run_until_pause)
- [x] implementation_service.py: reimplement(h)
- [x] state_machine.py: COMMAND_REQUIRES["reimplement"]
- [x] cli.py: slim run command + _render_runtime_result()
- [x] tests/test_runtime.py (4 tests)
- [x] **PHASE 10 GATE**

## Phase 11 — Contract and Patch Lifecycle Gates
- [x] schemas/task.py: WAITING_FOR_CONTRACT_APPROVAL, WAITING_FOR_PATCH_APPROVAL
- [x] state_machine.py: new transitions + COMMAND_REQUIRES entries
- [x] contract_service.py: build_contract → WAITING_FOR_CONTRACT_APPROVAL, approve_contract, reject_contract
- [x] implementation_service.py: implement → WAITING_FOR_PATCH_APPROVAL, approve_patch, reject_patch
- [x] db.py: update_patch_status()
- [x] cli.py: contract-approve, contract-reject, apply, patch-reject
- [x] runtime.py: pause after contract build + implement, auto_approve flag
- [x] server.py: 4 new MCP tools
- [x] **PHASE 11 GATE**

## Phase 12 — Event Log and harness trace
- [x] db.py: events table DDL + log_event, get_events, new_event_id
- [x] state_machine.py: emit state_transition events in transition()
- [x] runtime.py: _timed_service_call wrapper
- [x] cli.py: harness trace command
- [x] **PHASE 12 GATE**

## Phase 13 — LLM Robustness
- [x] llm.py: retry loop + _is_retriable, _call split, token tracking
- [x] config.py: max_tokens, llm_retries fields
- [x] cli.py: config set supports max_tokens, llm_retries
- [x] tests/test_llm.py (4 tests)
- [x] **PHASE 13 GATE**

## Phase 14 — Policy Engine
- [x] harness/policy.py (RiskLevel, PolicyDecision, DECISION_GATES, check_decision_gate, check_patch_risk)
- [x] runtime.py: integrate check_decision_gate before auto-approve
- [x] **PHASE 14 GATE**

## Phase 15 — Claude Code Syntax Executor Integration
- [x] harness/config.py: `use_claude_code: bool = True`, `claude_code_timeout: int = 300`
- [x] harness/services/claude_executor.py: 5 functions (is_claude_available, build_impl_prompt, run_claude_implement, capture_diff_staged, reset_allowed_files)
- [x] harness/services/implementation_service.py: implement() + reimplement() dispatch to Claude Code or LLM
- [x] harness/runtime.py: pass `config=config` to implement() and reimplement()
- [x] harness/cli.py: config-set handles use_claude_code/claude_code_timeout, implement shows mode, apply shows mode-aware message
- [x] harness/server.py: harness_implement tool passes config=config
- [x] harness/app.py: mode badge, mode-aware apply button, config toggles
- [x] tests/test_claude_executor.py: 13 tests
- [x] **PHASE 15 GATE**
