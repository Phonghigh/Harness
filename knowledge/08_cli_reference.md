# CLI Reference

All 13 commands. Entry point: `harness` (defined in pyproject.toml as `harness.cli:app`).

## harness init

```
harness init [--provider TEXT] [--model TEXT]
```

Creates `.harness/` directory, `config.json`, and `harness.db` in current directory.

- `--provider`: `anthropic` or `openai` (required — no default)
- `--model`: LLM model ID (e.g. `claude-sonnet-4-6`)

Required state: none (initializes the project)
Error: if `.harness/` already exists

Example:
```bash
harness init --provider anthropic --model claude-sonnet-4-6
```

## harness start

```
harness start REQUIREMENT
```

Creates a new task from a requirement string. Task starts in `INTAKE` state.

Required state: no active task (raises if one exists)
Error: "Active task T001 exists (status: WAITING_FOR_DECISIONS). Complete it first."

Example:
```bash
harness start "Add product CRUD with soft delete"
```

Output:
```
Task T8A3F2 created.
Title: Add product CRUD with soft delete
Status: INTAKE

Next: harness interrogate
```

## harness interrogate

```
harness interrogate
```

Calls Interrogator LLM (or stub in Phase 1). Generates decision map. Transitions: INTAKE → WAITING_FOR_DECISIONS.

Required state: INTAKE

Example output:
```
Interrogating requirement...

Decision Map (8 decisions generated):

ID    Category              Status    Question
D001  data_model            pending   What fields should Product have?
D002  api_contract          pending   Should API use DTOs or return entity directly?
D003  business_rules        pending   Can price be negative?
...

Next: harness decisions → harness answer D001 "..."
```

## harness decisions

```
harness decisions
```

Lists all decisions for the active task with current status.

Required state: WAITING_FOR_DECISIONS

Output: Rich table with ID, category, status, question, selected answer (if any), recommendation.

## harness answer

```
harness answer DECISION_ID [ANSWER_TEXT]
```

Records the human's answer for a decision. Transitions decision: pending → answered.

- `DECISION_ID`: e.g. `D001` (case-insensitive)
- `ANSWER_TEXT`: if omitted, launches interactive prompt with options

Required state: WAITING_FOR_DECISIONS

Example:
```bash
harness answer D001 "name, price, quantity, description"
harness answer D002   # interactive mode — shows options
```

## harness approve

```
harness approve DECISION_ID... [--all]
```

Approves one or more answered decisions. Transitions decision: answered → approved. If all decisions become approved, transitions task: WAITING_FOR_DECISIONS → DECISIONS_APPROVED.

- `DECISION_ID...`: one or more IDs
- `--all`: approves all answered (not pending) decisions at once (Phase 4)

Required state: WAITING_FOR_DECISIONS
Error: if decision is still `pending` (not answered yet)

Example:
```bash
harness approve D001 D002 D003
harness approve --all
```

## harness contract

```
harness contract
```

Builds implementation contract from all approved decisions. Calls Contract Builder LLM (or stub). Transitions: DECISIONS_APPROVED → CONTRACT_READY.

Required state: DECISIONS_APPROVED
Error: if any decision is not yet approved

Output:
```
Building contract...

Contract C001 created.
Scope: Product entity and DTO classes only.

Allowed files (3):
  src/.../Product.java
  src/.../CreateProductRequest.java
  src/.../ProductResponse.java

Forbidden:
  no controller, no service, no repository, no new dependencies

Next: harness implement C001
```

## harness implement

```
harness implement CONTRACT_ID
```

Generates unified diff patch by calling Syntax Executor LLM (or stub). Writes patch to `.harness/patches/<C-ID>.diff`. Transitions: CONTRACT_READY → IMPLEMENTING.

Required state: CONTRACT_READY

Output:
```
Generating patch...

Patch saved: .harness/patches/C001.diff
Lines added: 47, Lines removed: 0

Next: harness check C001
```

## harness check

```
harness check CONTRACT_ID
```

Runs compliance check on the patch. Two phases: rule-based + LLM (or stub). Transitions: IMPLEMENTING → CHECKING_COMPLIANCE → VALIDATING (pass) or → IMPLEMENTING (fail).

Required state: IMPLEMENTING

Output (pass):
```
Checking compliance...

Compliance: PASS

Rule-based: PASS (3 checks)
LLM review: PASS

No violations found.

Next: git apply .harness/patches/C001.diff → harness validate
```

Output (fail):
```
Compliance: FAIL

Violations:
  ERROR  scope_violation  File 'ProductRepository.java' not in allowed_files
  WARNING extra_scope     Method 'findByName()' not specified in contract

Task returned to IMPLEMENTING. Fix the contract or re-implement.
```

## harness validate

```
harness validate
```

Runs `validate_commands` from `.harness/config.json`. Transitions: VALIDATING → DONE (pass) or → IMPLEMENTING (fail).

Required state: CHECKING_COMPLIANCE or VALIDATING
Note: if no validate_commands configured → auto-PASS → DONE

Output:
```
Running validation...

pytest: PASS (12 tests, 0 failures)
ruff check .: PASS

All validation commands passed.

Next: harness remember
```

## harness remember

```
harness remember
```

Calls Memory Writer LLM (or stub). Extracts lessons from completed task. Saves to memory table.

Required state: DONE

Output:
```
Extracting lessons...

Saved 4 memories:
  project_standard  api_dto_policy    "API always uses DTO"
  architecture_rule price_validation  "Price must be >= 0"
  decision          delete_behavior   "Hard delete for now"
  lesson            scope_tip         "Entity-only tasks should not include service layer"
```

## harness memory list

```
harness memory list [--type TEXT] [--scope TEXT]
```

Lists stored memories.

- `--type`: filter by memory type (global_preference, project_standard, decision, lesson, architecture_rule)
- `--scope`: filter by scope (global, or project name)

## harness status

```
harness status
```

Shows current task state, decision coverage, and next step.

Output example:
```
Task T8A3F2: Add product CRUD [WAITING_FOR_DECISIONS]

Decision Coverage:
✓ data_model           (D001 approved)
✓ api_contract         (D002 approved)
△ business_rules       (D003 answered, not approved)
✗ error_handling       (not asked)
✗ implementation_scope (not asked)

Can implement: No
Reason: business_rules needs approval; error_handling and implementation_scope not resolved.

Next: harness answer D003 → harness approve D003
```

## Global Options

```
harness --help
harness --version
```

## Error Handling

All commands print errors to stderr and exit with code 1:
```
Error: No active task. Run 'harness start "requirement"' first.
Error: Task is in WAITING_FOR_DECISIONS, not INTAKE. Cannot run interrogate.
Error: HARNESS_PROVIDER not set. Set env var: export HARNESS_PROVIDER=anthropic
Error: ANTHROPIC_API_KEY not set.
```
