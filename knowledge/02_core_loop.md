# Core Loop

```
Ask → Decide → Contract → Syntax → Check → Remember
```

## Step 1: Ask

**Who:** AI (Interrogator role)
**What:** Extracts all decisions needed before implementation. Asks about every relevant decision category. Does NOT write code.
**Output:** `DecisionMap` — structured list of pending decisions grouped by category
**Gate:** `can_implement: false` — loop cannot proceed until all critical decisions are resolved

What good interrogation looks like:
- "What fields does Product have?" not "I'll add name, price, description"
- "Should delete be hard or soft?" not "I'll implement soft delete"
- Minimum 3 decisions, maximum 15 per task

What bad interrogation looks like:
- Writing any code
- Making architecture choices silently
- Skipping categories because "it's obvious"

## Step 2: Decide

**Who:** Human
**What:** Answers each decision question. Selects from options or writes a custom answer. Approves when satisfied.
**Output:** All decisions in `approved` status
**Gate:** Task cannot transition to `DECISIONS_APPROVED` until every decision is answered AND approved

Decision lifecycle:
```
pending → answered → approved
```

The human can reject a recommendation and pick differently. That choice is recorded.

## Step 3: Contract

**Who:** System (Contract Builder AI role)
**What:** Converts all approved decisions into a strict implementation contract
**Output:** `Contract` with scope, allowed_files, forbidden patterns, and spec
**Gate:** Contract cannot be created if any required decision is missing

The contract is a binding agreement. The Syntax Executor may not deviate from it.

Critical contract fields:
- `allowed_files` — exhaustive list; nothing else may be touched
- `forbidden` — patterns that must not appear in added lines
- `spec.files` — what each file should contain
- `spec.acceptance_criteria` — how to verify correctness

## Step 4: Syntax

**Who:** AI (Syntax Executor role)
**What:** Converts the contract into a unified diff patch. Reads only the contract + existing file contents.
**Output:** `.harness/patches/<C-ID>.diff`
**Gate:** Patch is NOT applied automatically. Human reviews before applying.

The Syntax Executor:
- Never sees the raw requirement
- Never makes design choices
- If the contract is ambiguous → outputs `ERROR: <reason>`, not a guess

## Step 5: Check

**Who:** System (Compliance Checker)
**What:** Verifies the patch follows the contract
**Output:** `ComplianceReport` with pass/fail and violation list
**Gate:** Patch is only applied after PASS

Two-phase checking:
1. Rule-based: file paths, forbidden patterns, dependency changes (deterministic)
2. LLM semantic: did AI add logic not in spec? (catches subtler drift)

Errors block progression. Warnings are surfaced but don't block.

## Step 6: Remember

**Who:** System (Memory Writer AI role)
**What:** Extracts reusable knowledge from the completed task
**Output:** Memory entries stored in SQLite
**Gate:** Only runs after task status = DONE

What gets saved:
- Project standards ("API always uses DTO")
- Architecture rules ("use BCrypt for passwords")
- Lessons learned ("when X, always ask Y first")
- Decision records (for future conflict detection)

## Forbidden Shortcuts

| Shortcut | Why it breaks the system |
|----------|--------------------------|
| INTAKE → IMPLEMENTING | No decisions, no contract → AI makes all choices |
| skip contract | Syntax Executor has no scope → AI adds features |
| auto-apply patch | Human loses final control |
| write memory before DONE | Lessons from failed/incomplete tasks are unreliable |
| hardcode prompt in Python | Cannot tune prompts without code change |
