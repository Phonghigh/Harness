# Architecture

## Module Dependency Graph

```
schemas/                 ← no dependencies (pure Pydantic)
  task.py                ← TaskStatus, Task, TaskCreate
  decision.py            ← Decision, DecisionMap, DECISION_CATEGORIES
  contract.py            ← Contract, ContractSpec, FileSpec
  compliance.py          ← ComplianceReport, Violation
         │
         ▼
config.py                ← pathlib, pydantic-settings, typer (for error only)
         │
         ▼
db.py                    ← sqlite3, schemas (for type hints), config (for db path)
         │
         ▼
state_machine.py         ← schemas/task.py only (TaskStatus enum)
         │
         ▼
llm.py                   ← anthropic, openai SDKs; importlib.resources for prompts
         │
         ▼
services/                ← db + state_machine + llm + all schemas
  task_service.py
  decision_service.py
  contract_service.py
  implementation_service.py
  validation_service.py
  memory_service.py
         │
         ▼
cli.py                   ← typer, rich, all services, config
```

**Hard rule:** Each layer may only import from layers above it. `cli.py` is the bottom; it imports everything. Nothing imports from `cli.py`.

## File Responsibilities

| File | Responsibility |
|------|----------------|
| `schemas/task.py` | TaskStatus enum, Task model, TaskCreate input model |
| `schemas/decision.py` | Decision model, DecisionMap (LLM output shape), DECISION_CATEGORIES list |
| `schemas/contract.py` | Contract, ContractSpec, FileSpec models |
| `schemas/compliance.py` | ComplianceReport, Violation, ViolationType |
| `config.py` | Find .harness root, load/save HarnessConfig, read env vars |
| `db.py` | All SQLite operations, ID generation, context manager conn |
| `state_machine.py` | Transition DAG, validate_transition, assert_command_allowed, transition() |
| `llm.py` | LLMAdapter ABC, AnthropicAdapter, OpenAIAdapter, load_prompt, extract_json_block |
| `services/task_service.py` | create_task, run_interrogate, get_active_task_or_exit |
| `services/decision_service.py` | list_decisions, answer_decision, approve_decisions |
| `services/contract_service.py` | build_contract (stub + LLM version) |
| `services/implementation_service.py` | implement (call syntax_executor, write .diff) |
| `services/validation_service.py` | check_compliance (2-phase), run_validate (subprocess) |
| `services/memory_service.py` | write_memory, list_memory, inject_project_memory |
| `cli.py` | Typer app, all commands, Rich output helpers, get_context() |

## Layer Rules

**schemas/** — zero imports from project code. Only stdlib + pydantic.

**config.py** — imports from pydantic-settings, pathlib, stdlib. No db or services.

**db.py** — imports from schemas (for type hints only), config (for paths). No services.

**state_machine.py** — imports from `schemas.task` only. No db, no llm.

**llm.py** — imports from anthropic/openai SDKs and importlib.resources. No db, no services.

**services/** — import from db, state_machine, llm, and schemas. Never from cli.py. Never from each other (avoid circular). If a service needs another service's data, pass it as a parameter.

**cli.py** — imports everything. This is the only place Rich and Typer belong.

## Why Services Must Be CLI-Free

Services are testable in isolation:
```python
# Test without CLI context:
task = {"id": "T001", "status": "INTAKE", ...}
db = Database(test_path)
decisions = run_interrogate(task, stub_llm, db)
assert len(decisions) > 0
```

If services imported Typer/Rich, they'd require CLI initialization to test. Keeps unit tests simple.

## config.py: find_harness_root Pattern

Walks up the directory tree to find `.harness/config.json`, just like `git` finds `.git`:

```python
def find_harness_root(start: Path = None) -> Path | None:
    current = start or Path.cwd()
    while True:
        candidate = current / ".harness" / "config.json"
        if candidate.exists():
            return current / ".harness"
        parent = current.parent
        if parent == current:   # reached filesystem root
            return None
        current = parent
```

This means `harness` commands work from any subdirectory of the project.
