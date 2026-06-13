# Applying Claude Memory Principles to an AI Agent System

**Date**: 2026-06-13  
**Project**: Harness  
**Tags**: #memory #prompt-engineering #python #sqlite #architecture #llm-agent  
**Difficulty**: hard

---

## The Problem

Harness already had a memory table and a `write_memory()` function, but the system learned poorly between tasks. Memory was only written once at `DONE`, injected indiscriminately into every prompt, had no formal taxonomy, and discarded the LLM's own reasoning (`rationale`, `confidence`). The challenge was to apply Claude Code's layered memory architecture — a well-documented external pattern — to an existing internal system without breaking the existing 69 tests.

---

## What Stuck Me

```
I assumed "having a memory table" = "having a good memory system".
The real gap: writing memory once at the end is like only taking notes
after the exam is over. All the micro-insights — why a human overrode
a recommendation, why a compliance check failed, which categories were
missed — happened mid-task and were silently discarded.

Second gap: injecting ALL memory into every prompt is noise, not signal.
An architecture_rule about "never use raw SQL" does not belong in the
context when answering a question about testing conventions.
```

---

## Approaches Researched

| Approach | Why Considered | Why Rejected / Accepted |
|----------|---------------|------------------------|
| Single batch write at DONE (current) | Simple, one LLM call | Rejected: loses all mid-task events |
| Write memory after every LLM call | Maximum granularity | Rejected: too noisy, would duplicate lessons |
| Event-driven writes at key lifecycle points | Matches how learning actually happens | **Accepted: surgical, no duplication** |
| Inject all memory always | Simple, nothing missed | Rejected: prompt bloat, irrelevant context crowds out relevant |
| Load memory on demand (RAG-style) | Maximum precision | Rejected: over-engineering for current scale |
| **Category-scoped injection** | Balance relevance vs simplicity | **Accepted: filter by decision category + always include anchors** |

---

## The Solution

### Pattern 1: Layered Memory Taxonomy

**Name**: Formal type taxonomy with lifecycle tiers  
**Category**: architectural

Define a fixed set of memory types where each type has a clear purpose, scope, and lifetime. Separate `type` (what kind of knowledge) from `category` (which decision domain it belongs to). This is exactly how Claude Code's memory system works: user / project / path-scoped / feedback / reference are distinct layers.

```python
MEMORY_TYPES = [
    "project_standard",    # Permanent — stable architectural decisions
    "architecture_rule",   # Permanent — hard constraints
    "feedback",            # Permanent — human override rationales
    "compliance_pattern",  # Semi-permanent — recurring violation fixes
    "interrogation_pattern", # Semi-permanent — which categories to ask for
    "lesson",              # Semi-permanent — soft learnings
]
```

### Pattern 2: Event-Driven Incremental Memory

**Name**: Write-at-event, not write-at-end  
**Category**: architectural

Instead of one batch LLM write at task completion, add lightweight (no-LLM) writes at 4 specific lifecycle events. Each event produces a typed memory entry immediately.

```python
def write_event_memory(event_type: str, data: dict, db: Database, config) -> None:
    # event_type: "conflict_override" | "compliance_failure" | "compliance_success"
    # Direct DB write, no LLM call, no latency
    entry = {
        "type": mem_type,   # derived from event_type
        "category": ...,    # decision domain
        "key": _slugify(...),
        "value_json": json.dumps({"lesson": ..., "context": ...}),
    }
    db.upsert_memory(entry)
```

### Pattern 3: Category-Scoped Injection

**Name**: Anchor + scoped context injection  
**Category**: prompt-engineering

When answering a decision in category X, inject only:
- All `project_standard` + `architecture_rule` (anchors — always relevant)
- Memories with `category == X` (directly relevant)

```python
def inject_project_memory(db, scope=None, category=None) -> str:
    if category:
        anchors = db.list_memory(type_filter="project_standard") + \
                  db.list_memory(type_filter="architecture_rule")
        scoped  = db.list_memory(category_filter=category)
        memories = deduplicate(anchors + scoped)
    else:
        memories = db.list_memory()   # legacy: full inject for interrogation
    ...
```

---

## Before vs After

### Before

```
Task lifecycle:
INTAKE → INTERROGATING → DECISIONS → CONTRACT → IMPLEMENT → DONE
                                                              │
                                                              └─ write_memory() [1 LLM call]
                                                                 → 2-6 lesson entries

inject_project_memory():
  list_memory() → ALL rows → format → inject into prompt
  (200 rows? 200 rows injected. Relevant? Doesn't matter.)
```

**Problems with before:**
- Human overrides an LLM recommendation → reason is **silently lost**
- Compliance fails with 3 error violations → pattern is **never recorded**
- Conflict detected but human approves anyway → rationale is **discarded**
- `decision_answerer.md` LLM outputs `rationale` + `confidence` → code reads `selected_answer` only, **throws the rest away**
- `evaluation_service.py` computes "missed categories: [security_permission, testing]" → **number is shown once and forgotten**

### After

```
Task lifecycle:
INTAKE
  └─ interrogate()       → inject_project_memory(category=None)  [full context for question gen]
DECISIONS
  └─ auto_answer()       → inject_project_memory(category=dec["category"])  [scoped per decision]
  └─ answer_decision()   → if answer ≠ recommendation → write feedback memory  [instant, no LLM]
  └─ approve_decisions() → if conflict detected → write conflict_override memory [instant, no LLM]
CONTRACT → IMPLEMENT
COMPLIANCE CHECK
  └─ check_compliance()  → if failed → write compliance_pattern per error violation [instant, no LLM]
DONE
  └─ write_memory()      → LLM extracts 2-6 lessons [existing, now with type taxonomy]
EVALUATION
  └─ compute_evaluation()→ if categories_missing → write interrogation_pattern [instant, no LLM]
                         → if retries >= 2       → write compliance_pattern     [instant, no LLM]
                         → if first_pass_success → write lesson                 [instant, no LLM]
```

**Improvements:**
- Every human override is permanently recorded with full context
- Compliance failures produce reusable `compliance_pattern` memories immediately
- `rationale` + `confidence` from LLM are stored in the `decisions` table
- Evaluation metrics feed back into future behavior instead of being discarded
- Each decision auto-answer sees only relevant memory (scoped by category)

### Visual Comparison

```
BEFORE: inject_project_memory()
────────────────────────────────────────────────────────
  All 200 memory entries
         │
         ▼
  [testing lesson]   [data_model rule]   [api lesson]
  [arch rule]        [security pattern]  [validation]
         │
         ▼
  Answering: "What data model to use?"
  Receives: testing lessons + security patterns + api lessons + ...
  → NOISE drowns signal

AFTER: inject_project_memory(category="data_model")
────────────────────────────────────────────────────────
  Step 1: Always load anchors
  ┌─────────────────────────────────┐
  │ project_standard (all)          │ ← permanent architectural decisions
  │ architecture_rule (all)         │ ← hard constraints
  └─────────────────────────────────┘
  Step 2: Load category-specific
  ┌─────────────────────────────────┐
  │ category = "data_model"         │ ← directly relevant
  └─────────────────────────────────┘
  Step 3: Deduplicate + inject
         │
         ▼
  Answering: "What data model to use?"
  Receives: data_model memories + architectural anchors only
  → SIGNAL without noise
```

---

## Architecture Change

```
MEMORY WRITE POINTS — BEFORE vs AFTER
══════════════════════════════════════════════════════════════════

BEFORE:                              AFTER:
─────────────────────────────────    ────────────────────────────────────────────
task.DONE                            task.INTAKE
    │                                    │ interrogate()
    ▼                                    │   └─ inject (full memory, no filter)
write_memory() [LLM]                     │
    │                                task.WAITING_FOR_DECISIONS
    ▼                                    │ answer_decision()
  2-6 lesson entries                     │   └─ if answer ≠ recommendation
  written once                           │       → write FEEDBACK memory  ← NEW
                                         │ approve_decisions()
                                         │   └─ if conflict detected
                                         │       → write FEEDBACK memory  ← NEW
                                         │
                                     task.CHECKING_COMPLIANCE
                                         │ check_compliance()
                                         │   └─ if failed (error violations)
                                         │       → write COMPLIANCE_PATTERN  ← NEW
                                         │
                                     task.DONE
                                         │ write_memory() [LLM]
                                         │   └─ 2-6 typed entries (new taxonomy)
                                         │
                                     task.DONE → evaluation
                                         │ compute_evaluation()
                                         │   └─ if missing categories
                                         │       → write INTERROGATION_PATTERN  ← NEW
                                         │   └─ if retries >= 2
                                         │       → write COMPLIANCE_PATTERN  ← NEW
                                         │   └─ if first_pass_success
                                         │       → write LESSON  ← NEW
```

**What changed:**

| File | Change |
|------|--------|
| `schemas/decision.py` | Added `MEMORY_TYPES` constant + `rationale`, `confidence` fields to `Decision` |
| `db.py` | DB migration adds `rationale`, `confidence` columns to decisions table |
| `services/memory_service.py` | `inject_project_memory()` gains `category` param; new `write_event_memory()` helper |
| `services/decision_service.py` | `answer_decision()` writes feedback on override; `approve_decisions()` writes on conflict |
| `services/validation_service.py` | `check_compliance()` writes compliance_pattern on error violations |
| `services/evaluation_service.py` | `compute_task_evaluation()` derives 3 memory types from metrics |
| `prompts/memory_writer.md` | Prompt updated: outputs `type` (MEMORY_TYPES) + `category` (DECISION_CATEGORIES) |
| `cli.py` | New `harness memory summary [--write]` command |

---

## Why This Is Better

| Dimension | Before | After |
|-----------|--------|-------|
| Write frequency | 1× per task (at DONE) | 1 + N events (mid-task + DONE) |
| Memory taxonomy | Freeform string | 6 formal types with lifecycles |
| Context relevance | All memory injected always | Category-scoped + permanent anchors |
| Human override capture | Lost silently | `feedback` memory written instantly |
| LLM rationale | Discarded | Stored in `decisions.rationale` + `decisions.confidence` |
| Evaluation learning | Metrics computed, then discarded | Metrics → memory entries automatically |
| Memory discoverability | Flat dump (`list`) | Grouped index (`summary`) |
| Tests | 69 passed | 90 passed |

---

## Key Takeaways

1. **"Having a memory table" ≠ "learning system"** — writing once at the end captures conclusions but loses the process. Learning happens mid-task; memory writes should match that.

2. **Inject only what is relevant to the current context** — the Claude Code pattern of path-scoped rules applies directly to prompt injection: use category as the scope filter, always include "anchor" memories (project_standard, architecture_rule), inject everything else only when in context.

3. **Event-driven writes beat batch writes for granularity** — lightweight (no-LLM) writes at key lifecycle events are faster, cheaper, and more precise than asking the LLM to extract everything at the end. Save the LLM call for soft lessons that require synthesis.

4. **Separate `type` from `category`** — `type` answers "what kind of knowledge is this?"; `category` answers "which domain does this belong to?". Conflating them (as the original code did) prevents both good taxonomy and good filtering.

5. **Evaluation metrics are wasted if they don't feed back into behavior** — `evaluation_service.py` computed "missed categories" and "high retry count" but the information died there. Closing the loop: metrics → memory → next task's context is a small code change with large learning impact.

---

## Related Problems / Patterns

- [[claude-code-memory-guide]] — Claude Code's layered memory: user/project/path/feedback/reference
- [[prompt-context-management]] — Managing what goes into LLM context windows
- [[event-driven-architecture]] — Write-at-event pattern
- [[karpathy-guidelines]] — Surgical changes, goal-driven execution

---

## Next Time Checklist

- [ ] When adding a memory system: define taxonomy first (types + lifecycle), then write paths
- [ ] Before injecting context into a prompt: ask "is ALL of this relevant to THIS call?"
- [ ] When metrics are computed: always ask "does this metric feed back into future behavior?"
- [ ] Check if the LLM already produces useful fields that are being discarded (rationale, confidence, etc.)
- [ ] Add `write_event_memory()` helper immediately when building any event-driven learning system — it costs nothing at call sites
