# Database Schema

SQLite. No ORM. `sqlite3.Row` for dict-like access. All writes wrapped in context manager.

## Tables

### tasks
```sql
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,    -- e.g. T8A3F2 (T + 6 hex chars)
    title       TEXT NOT NULL,
    raw_requirement TEXT NOT NULL,
    status      TEXT NOT NULL,       -- TaskStatus enum value
    created_at  TEXT NOT NULL,       -- ISO 8601
    updated_at  TEXT NOT NULL
);
```

### decisions
```sql
CREATE TABLE IF NOT EXISTS decisions (
    id              TEXT PRIMARY KEY,  -- e.g. D001 (D + zero-padded count)
    task_id         TEXT NOT NULL,
    category        TEXT NOT NULL,     -- one of 15 taxonomy IDs
    question        TEXT NOT NULL,
    options_json    TEXT NOT NULL,     -- JSON array of option strings
    recommendation  TEXT,
    selected_answer TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|answered|approved
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

### contracts
```sql
CREATE TABLE IF NOT EXISTS contracts (
    id                   TEXT PRIMARY KEY,  -- e.g. C001
    task_id              TEXT NOT NULL,
    scope                TEXT NOT NULL,     -- one-line summary
    allowed_files_json   TEXT NOT NULL,     -- JSON array of file paths
    forbidden_json       TEXT NOT NULL,     -- JSON array of forbidden patterns
    spec_json            TEXT NOT NULL,     -- full ContractSpec as JSON
    status               TEXT NOT NULL DEFAULT 'draft',  -- draft|ready|approved
    created_at           TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

### patches
```sql
CREATE TABLE IF NOT EXISTS patches (
    id           TEXT PRIMARY KEY,  -- e.g. P001
    contract_id  TEXT NOT NULL,
    diff_text    TEXT NOT NULL,     -- raw unified diff content
    status       TEXT NOT NULL,     -- generated|applied|rejected
    created_at   TEXT NOT NULL,
    FOREIGN KEY (contract_id) REFERENCES contracts(id)
);
```

### compliance_reports
```sql
CREATE TABLE IF NOT EXISTS compliance_reports (
    id             TEXT PRIMARY KEY,
    contract_id    TEXT NOT NULL,
    patch_id       TEXT NOT NULL,
    passed         INTEGER NOT NULL,   -- 0 or 1
    violations_json TEXT,              -- JSON array of Violation objects
    summary        TEXT,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (contract_id) REFERENCES contracts(id),
    FOREIGN KEY (patch_id)    REFERENCES patches(id)
);
```

### memory
```sql
CREATE TABLE IF NOT EXISTS memory (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL,   -- global_preference|project_standard|decision|lesson|architecture_rule|validation_command|conflict
    scope       TEXT NOT NULL,   -- 'global' or project_name
    key         TEXT NOT NULL,   -- e.g. "api_dto_policy"
    value_json  TEXT NOT NULL,   -- JSON value
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(type, scope, key)     -- upsert target
);
```

## ID Generation

```python
# Task IDs: T + 6 random hex chars (UUID-based, not sequential)
task_id = "T" + uuid.uuid4().hex[:6].upper()  # e.g. T8A3F2

# Decision IDs: D + zero-padded sequential count scoped to task
# count = SELECT COUNT(*) FROM decisions WHERE task_id = ?
decision_id = f"D{(count + 1):03d}"  # D001, D002, ...

# Contract IDs: C + zero-padded global sequential count
# count = SELECT COUNT(*) FROM contracts
contract_id = f"C{(count + 1):03d}"  # C001, C002, ...

# Patch IDs: P + zero-padded global sequential count
patch_id = f"P{(count + 1):03d}"
```

## Context Manager Pattern

All DB operations use this pattern. Never call `conn.commit()` manually.

```python
@contextmanager
def connect(self):
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

## Key Query Patterns

### Get active task (single non-DONE task)
```python
def get_active_task(self) -> sqlite3.Row | None:
    with self.connect() as conn:
        return conn.execute(
            "SELECT * FROM tasks WHERE status != 'DONE' LIMIT 1"
        ).fetchone()
```

### Upsert memory (insert-or-replace on unique key)
```python
def upsert_memory(self, entry: dict) -> None:
    with self.connect() as conn:
        conn.execute("""
            INSERT INTO memory (id, type, scope, key, value_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(type, scope, key)
            DO UPDATE SET value_json = excluded.value_json,
                         updated_at = excluded.updated_at
        """, (...))
```

### Check if all decisions approved
```python
def get_pending_decisions(self, task_id: str) -> list[sqlite3.Row]:
    with self.connect() as conn:
        return conn.execute(
            "SELECT * FROM decisions WHERE task_id = ? AND status != 'approved'",
            (task_id,)
        ).fetchall()
# If this returns empty list → all approved → can transition to DECISIONS_APPROVED
```

## Timestamps

All timestamps stored as ISO 8601 strings:
```python
from datetime import datetime, timezone
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
```
