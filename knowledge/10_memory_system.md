# Memory System

Structured memory that persists across tasks. Not chat history. Typed, scoped, and queryable.

## Memory Types

| Type | Meaning | Example |
|------|---------|---------|
| `global_preference` | User's universal preferences for AI behavior | "Never auto-apply patches" |
| `project_standard` | Architectural decisions that apply to all tasks in this project | "API always uses DTO" |
| `decision` | A specific decision made in a past task (for reference and conflict detection) | "Auth uses JWT RS256" |
| `lesson` | Something learned from a past task — a pattern or anti-pattern | "Entity-only tasks should not include service layer in scope" |
| `architecture_rule` | A hard rule derived from past decisions | "BCrypt for all password hashing, never MD5" |
| `validation_command` | Commands to run for validation in this project | `pytest tests/` |
| `conflict` | A case where the human overrode a project standard with reason | "Used sessions instead of JWT for admin panel — simpler for this endpoint" |

## Scope

Every memory entry has a `scope`:
- `"global"` — applies to all projects (personal preferences)
- `"<project_name>"` — applies only to this project

The `project_name` comes from `HarnessConfig.project_name`.

## Upsert-by-Key Rule

Memory entries are identified by `(type, scope, key)`. Writing a memory entry with the same key updates the value rather than creating a duplicate.

This means:
- `write_memory("project_standard", "my-project", "api_dto_policy", ...)` always overwrites the previous value for that key
- Never creates duplicate entries for the same concept
- History is NOT preserved — only the latest value

## Memory Injection into Interrogator

Before calling the Interrogator LLM, load relevant project memory and inject it as context:

```python
def inject_project_memory(db: Database, project_name: str) -> str:
    memories = db.list_memory(scope=project_name)
    if not memories:
        return "(none)"
    lines = []
    for m in memories:
        lines.append(f"[{m['type']}] {m['key']}: {json.loads(m['value_json'])}")
    return "\n".join(lines)
```

This string is injected into the interrogator prompt as:
```
EXISTING PROJECT STANDARDS:
[project_standard] api_dto_policy: API always uses DTO
[architecture_rule] auth_method: JWT RS256 for all endpoints
[decision] delete_behavior: Hard delete for now
```

The interrogator uses this to:
1. Skip asking about decisions already resolved (e.g., don't ask about auth if it's in memory)
2. Reference memory in recommendations (e.g., "Based on project standard, recommend DTO")
3. Mark decisions as `memory_informed: true` in the output

## Conflict Detection

When `harness approve D00X "answer"` is called, check the answer against memory:

```python
def check_for_conflict(answer: str, category: str, db: Database, project: str) -> str | None:
    """Returns conflict description if answer contradicts memory, else None."""
    memories = db.list_memory(scope=project, type_="project_standard")
    memories += db.list_memory(scope=project, type_="architecture_rule")
    # Simple keyword check — LLM-based check can be added later
    for m in memories:
        if m["category"] == category:
            stored = json.loads(m["value_json"])
            if conflicts(answer, stored):   # domain-specific logic
                return f"Conflicts with {m['type']} '{m['key']}': {stored}"
    return None
```

If a conflict is detected:
```
⚠ D002 answer "Use sessions" conflicts with project_standard 'auth_method': JWT RS256.
  Override project standard? [y/N]
```

If user confirms override, save a `conflict` memory:
```python
db.upsert_memory({
    "type": "conflict",
    "scope": project_name,
    "key": f"override_{decision_id}",
    "value_json": json.dumps({
        "decision": decision_id,
        "answer": answer,
        "overrides": memory_key,
        "reason": "User confirmed override"
    })
})
```

## harness memory search

```bash
harness memory search "JWT"
```

Simple `LIKE '%JWT%'` search over `key` and `value_json` columns. Returns matching rows.

## harness memory delete

```bash
harness memory delete <memory-id>
```

Deletes a single memory entry by ID. The only way to delete memory (never done programmatically otherwise).

## Memory Table Schema

```sql
CREATE TABLE memory (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,
    scope       TEXT NOT NULL,
    key         TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(type, scope, key)
);
```

The `UNIQUE(type, scope, key)` constraint enables the `ON CONFLICT DO UPDATE` upsert pattern.
