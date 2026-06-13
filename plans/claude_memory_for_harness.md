# Claude Memory Principles Applied to Harness Agent

## Analysis: What Harness Has vs. What Claude Memory Teaches

### Current Memory System

| Component | What it does |
|-----------|-------------|
| `memory` table | `type, scope, key, value_json, category, source_task_id, applied_count, last_applied_at` |
| `write_memory()` | LLM extracts lessons after task reaches DONE state |
| `inject_project_memory()` | Dumps ALL memory into interrogator + decision_answerer prompts |
| `search_memory()` | Case-insensitive full-text search |
| `conflict_service.py` | Detects when new answers contradict stored memory |
| `evaluate_service.py` | Computes metrics but writes NO memories from them |

### Gap Analysis vs Claude Memory Principles

| Claude Principle | Harness Gap | Impact |
|-----------------|-------------|--------|
| Layered memory types | Flat `type` string, no formal taxonomy | Wrong context bleeds into unrelated decisions |
| Feedback memory (capture corrections AND confirmations) | Human overrides lose the WHY | LLM keeps making the same wrong recommendations |
| Scoped/on-demand loading | `inject_project_memory()` dumps everything | Prompt bloat; irrelevant memories crowd out relevant ones |
| Auto memory at key lifecycle events | Memory only written after DONE | Compliance failures, conflict overrides, and mid-task insights are lost |
| MEMORY.md index pattern | No index; list_memory is a flat dump | No way to scan what's stored |
| Evaluation → memory pipeline | evaluation_service.py writes no memories | Patterns never feed back into future behavior |
| Category-scoped injection | All memories injected regardless of active category | architecture_pattern memory injected when answering testing question |

---

## The 7 Phases

### Phase G — Decision Rationale Persistence

**Problem**: `decision_answerer.md` outputs `confidence` and `rationale` fields but `auto_answer_decisions()` discards them.

**Changes**:
- `harness/schemas/decision.py`: Add `rationale: str | None` and `confidence: str | None` fields
- `harness/db.py`: Migration adds `rationale TEXT`, `confidence TEXT` columns to decisions table
- `harness/db.py`: Update `create_decision()` INSERT to include new columns
- `harness/services/task_service.py`: Add `rationale: None, confidence: None` to decision dict
- `harness/services/decision_service.py`: Persist rationale + confidence from `_DecisionAnswer`; add `rationale: None, confidence: None` to stub decisions

### Phase A — Memory Type Taxonomy

**Problem**: `memory.type` is a freeform string set to DECISION_CATEGORIES values. No formal taxonomy.

**6 canonical MEMORY_TYPES**:
- `project_standard` — Stable architectural decisions (permanent)
- `architecture_rule` — Hard constraints (permanent)
- `feedback` — Human override rationales (permanent)
- `compliance_pattern` — Recurring violation fixes (semi-permanent)
- `interrogation_pattern` — Which categories fire for certain requirement types (semi-permanent)
- `lesson` — Soft learnings from past tasks (semi-permanent)

**Changes**:
- `harness/schemas/decision.py`: Add `MEMORY_TYPES` constant (6 strings)
- `harness/services/memory_service.py`: Update `_MemoryItem` to include `type` field (separate from `category`); update `write_memory()` to use `mem.type`
- `harness/prompts/memory_writer.md`: Output both `type` (from MEMORY_TYPES) and `category` (from DECISION_CATEGORIES) fields

### Phase B — Feedback Memory (Human Override Capture)

**Problem**: When human selects an answer different from LLM recommendation, no memory is written.

**Trigger**: `answer_decision()` in `decision_service.py` — if `answer != decision["recommendation"]`, write a `feedback` memory immediately (no LLM).

**Memory written**:
```json
{
  "type": "feedback",
  "category": "{decision_category}",
  "key": "override_{category}_{decision_id}",
  "value_json": {"lesson": "...", "context": "...", "recommendation_rejected": "...", "answer_chosen": "..."}
}
```

**Changes**:
- `harness/services/decision_service.py`: Add `_write_feedback_memory()` helper; call it from `answer_decision()` when answer differs from recommendation

### Phase C — Category-Scoped Memory Injection

**Problem**: `inject_project_memory()` injects all memory into every prompt regardless of relevance.

**New behavior**: When `category` is provided, inject only:
- Memories matching that category
- All `project_standard` and `architecture_rule` memories (always relevant)

**Changes**:
- `harness/services/memory_service.py`: Add `category: str | None = None` param to `inject_project_memory()`
- `harness/services/decision_service.py`: Pass `category=dec["category"]` in `auto_answer_decisions()`

### Phase D — Incremental Memory at Key Events

**Problem**: Memory only written at DONE. Compliance failures, conflict overrides, and first-pass successes are never captured.

**3 new write points** (all direct DB writes, no LLM):
1. **Conflict override**: In `approve_decisions()`, when conflict detected but human approves anyway
2. **Compliance failure**: After compliance check fails (error-level violations only)
3. **First-pass success**: After compliance passes on first try

**Changes**:
- `harness/services/memory_service.py`: Add `write_event_memory(event_type, data, db, config)` helper
- `harness/services/decision_service.py`: Call `write_event_memory("conflict_override", ...)` in `approve_decisions()`
- `harness/services/validation_service.py`: Call `write_event_memory("compliance_failure", ...)` when `passed == False`

### Phase E — Evaluation → Memory Pipeline

**Problem**: `evaluation_service.py` computes metrics but the patterns it discovers (missed categories, high retry count) never feed back into future behavior.

**3 derived memories from evaluation** (no LLM):
- E1: If `categories_missing` has items → write `interrogation_pattern` memory
- E2: If `compliance.total_retries >= 2` → write `compliance_pattern` memory
- E3: If `passed_on_first_try == True` → write `lesson` memory (success baseline)

**Changes**:
- `harness/services/evaluation_service.py`: Add `_write_evaluation_memories(evaluation, task, db, config)` called after `create_evaluation()`

### Phase F — Memory Index (MEMORY.md Pattern)

**Problem**: No way to quickly scan what's in memory. `harness memory list` is a flat dump with no structure.

**New command**: `harness memory summary [--write]`
Prints a grouped one-line index by type:
```
## project_standard (3)
- [M1A2B3] use_repository_pattern — Use repo pattern for data access (from T001, applied 4×)

## feedback (2)
- [M4C5D6] override_data_model_dto — Human chose domain objects over DTO (from T002)
```

`--write` flag writes `.harness/MEMORY.md` in addition to printing.

**Changes**:
- `harness/cli.py`: Add `memory summary [--write]` subcommand

---

## Implementation Order

G → A → B → C → F → D → E

(Schema changes first, then writes, then reads/injection, then pipelines)

## Verification

```bash
# Phase G
python -c "from harness.schemas.decision import Decision; assert 'rationale' in Decision.model_fields; print('G OK')"

# Phase A
python -c "from harness.schemas.decision import MEMORY_TYPES; assert 'feedback' in MEMORY_TYPES; print('A OK')"

# Full suite
pytest tests/ -q

# Manual
harness memory summary
```

## Files Modified

| File | Phases |
|------|--------|
| `harness/schemas/decision.py` | G, A |
| `harness/db.py` | G |
| `harness/services/task_service.py` | G |
| `harness/services/decision_service.py` | G, B, C, D |
| `harness/services/memory_service.py` | A, C, D |
| `harness/services/evaluation_service.py` | E |
| `harness/services/validation_service.py` | D |
| `harness/prompts/memory_writer.md` | A |
| `harness/cli.py` | F |
