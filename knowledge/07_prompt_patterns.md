# Prompt Patterns (Skills Catalog)

5 reusable patterns for building the Harness system. Apply consistently across all files.

---

## SK-1: Prompt Boundary Pattern

**Use for:** Every prompt template in `harness/prompts/*.md`

**Structure:**
```markdown
# Role
You are a [very specific, narrow role]. You do NOT [explicit list of forbidden behaviors].

# Output
Output [format] ONLY. No explanation. No markdown fences around the output.

# Schema
[exact JSON schema or format spec]

# Failure Mode
If you cannot produce valid output, return: {"error": "reason"}
Never guess. Never invent fields. Return the error object instead.

---USER---
{input_placeholder}
```

**Why:** LLMs drift toward helpfulness — they add explanation, code, and "bonus" features. A hard role definition + forbidden list + explicit failure mode keeps output machine-parseable.

**Worked Example (interrogator.md):**
```markdown
# Role
You are a Requirement Interrogator. You do NOT write code. You do NOT suggest implementations. You do NOT choose options on behalf of the human.

# Output
Output JSON ONLY. No explanation before or after. No markdown fences.

# Schema
{
  "decisions": [
    {
      "category": "<taxonomy ID>",
      "question": "<specific question>",
      "options": ["<option A>", "<option B>"],
      "recommendation": "<recommended option and why>"
    }
  ],
  "rationale": "<why you identified these decisions>"
}

# Failure Mode
If the requirement is too vague to extract decisions, return:
{"error": "requirement too vague: <specific reason>"}

---USER---
REQUIREMENT:
{requirement}

EXISTING PROJECT STANDARDS:
{project_memory}
```

---

## SK-2: State Gate Pattern

**Use for:** Every service function that changes task state

**Structure:**
```python
def service_fn(task: dict, ..., db: Database) -> Result:
    # 1. Assert current state allows this command
    assert_command_allowed("command_name", TaskStatus(task["status"]))
    
    # 2. Do the work
    result = ...
    
    # 3. Transition to next state (validates transition internally)
    transition(task, TaskStatus.NEXT_STATE, db)
    
    return result
```

**Why:** State checks in the service layer (not CLI) protect against programmatic misuse, not just CLI misuse. A future API or test that calls the service directly also gets the guard.

**Worked Example (decision_service.py):**
```python
def approve_decisions(decision_ids: list[str], task: dict, db: Database) -> None:
    assert_command_allowed("approve", TaskStatus(task["status"]))
    
    for d_id in decision_ids:
        d = db.get_decision(d_id)
        if not d:
            raise ValueError(f"Decision {d_id} not found")
        if d["status"] != "answered":
            raise ValueError(f"Decision {d_id} must be answered before approving")
    
    db.approve_decisions(decision_ids)
    
    # Auto-transition if all decisions now approved
    remaining = db.get_pending_decisions(task["id"])
    if not remaining:
        transition(task, TaskStatus.DECISIONS_APPROVED, db)
```

---

## SK-3: Two-Phase Compliance Pattern

**Use for:** `validation_service.check_compliance()`

**Structure:**
```python
def check_compliance(contract, patch_content, llm, db):
    # Phase 1: Rule-based (deterministic, free, fast)
    rule_violations = _rule_based_check(contract, patch_content)
    rule_passed = not any(v.severity == "error" for v in rule_violations)
    
    # Phase 2: LLM semantic review (catches subtler violations)
    llm_result = _llm_semantic_check(contract, patch_content, rule_violations, llm)
    
    # Merge: all violations from both phases
    all_violations = rule_violations + llm_result.violations
    passed = rule_passed and llm_result.passed
    
    return ComplianceReport(passed=passed, violations=all_violations, ...)
```

**Rule-based checks (Phase 1):**
1. Parse `+++ b/<path>` lines from unified diff → list of modified files
2. Assert every modified file is in `contract.allowed_files`
3. Scan all `+` (added) lines for forbidden pattern matches (case-insensitive)
4. Verify each `FileSpec` in contract has at least one corresponding hunk

**Why:** LLM alone is unreliable for exact path matching. Rules alone miss semantic drift (e.g., AI adds a method not in spec). Two phases together are cheap and accurate. Rule findings are injected into LLM prompt so LLM can give context without overriding.

---

## SK-4: JSON Fence Extraction Pattern

**Use for:** Every LLM response that contains JSON

**Structure:**
```python
def extract_json_block(text: str) -> str:
    """Strip ```json ... ``` fences; fall back to raw text."""
    import re
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    return match.group(1) if match else text.strip()

# Always use model_validate_json, never json.loads:
raw = extract_json_block(llm_response.content)
try:
    result = MyModel.model_validate_json(raw)
except ValidationError as e:
    raise LLMOutputError(f"LLM returned invalid schema: {e}") from e
```

**Why:** `model_validate_json()` gives type validation + a readable error message showing exactly which field was wrong. `json.loads()` crashes with an opaque "Expecting value: line 1 column 1" when the LLM adds explanation before the JSON.

**Worked Example:**
```python
response = llm.complete(system=system_prompt, user=user_content)
raw = extract_json_block(response.content)
try:
    decision_map = DecisionMap.model_validate_json(raw)
except ValidationError as e:
    typer.echo(f"Error: LLM response was not a valid DecisionMap.\n{e}", err=True)
    raise typer.Exit(1)
```

---

## SK-5: Context Manager DB Pattern

**Use for:** Every function in `db.py`

**Structure:**
```python
def some_db_operation(self, ...) -> ...:
    with self.connect() as conn:
        result = conn.execute("SELECT ...", params).fetchall()
        # conn.commit() called automatically on exit
    return result
```

**Never do:**
```python
conn = sqlite3.connect(self.db_path)
conn.execute(...)
conn.commit()   # ← manual commit: risky, easy to forget
conn.close()    # ← manual close: leaks on exception
```

**Multi-step writes in one transaction:**
```python
def create_task_with_decisions(self, task: dict, decisions: list[dict]) -> None:
    with self.connect() as conn:
        # Both inserts are in the same transaction
        conn.execute("INSERT INTO tasks ...", task_params)
        for d in decisions:
            conn.execute("INSERT INTO decisions ...", d_params)
    # Either both commit or both rollback
```

**Why:** Prevents partial writes when multi-step operations fail mid-way. Ensures every connection is properly closed even if an exception occurs.
