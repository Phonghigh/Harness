# Architect-Driven Coding Harness — Agent Context

## What This Is

A decision-first AI coding system. Humans own all architecture decisions. AI converts approved contracts into syntax — never requirements directly into code.

Core loop (IMMUTABLE):
```
Ask → Decide → Contract → Syntax → Check → Remember
```

## Non-Negotiable Rules (read before every task)

1. State machine is the gatekeeper — commands that skip states must **raise**, not warn
2. No LLM call before state allows it: interrogate=INTAKE, contract=DECISIONS_APPROVED, implement=CONTRACT_READY
3. Syntax Executor reads contract JSON only — never raw requirement
4. Compliance check runs before any `git apply`
5. Patch files go to `.harness/patches/` — never auto-applied
6. One active task at a time (MVP)
7. Memory written only after DONE
8. Prompt templates in `harness/prompts/*.md` — never hardcoded in Python
9. All LLM output parsed via `model_validate_json()` — never bare `json.loads()`
10. Services never import from `cli.py` — only CLI imports services

## Karpathy Coding Guidelines

Four principles from Andrej Karpathy's LLM coding observations — enforced on every task.

**1. Think Before Coding** — Surface assumptions before writing any code. If a requirement is ambiguous, name the ambiguity and ask. Never pick silently between interpretations.

**2. Simplicity First** — Minimum code that solves the stated problem. No speculative features, no abstractions for single-use code, no error handling for impossible scenarios. If it could be 50 lines, don't write 200.

**3. Surgical Changes** — Every changed line must trace directly to the user's request. Don't improve adjacent code, don't reformat, don't refactor what isn't broken. Remove only the orphans YOUR changes created.

**4. Goal-Driven Execution** — Define a verifiable success criterion before starting. For each phase item the criterion is the Phase Verification Gate command — the item is not done until that command passes.

> Invoke with `/karpathy-guidelines` or `Skill(karpathy-guidelines)` for the full reference with examples.

## Architecture (build strictly in this order)

```
schemas/         ← no deps (done ✓)
    task.py      ✓
    decision.py  ✓
    contract.py  ✓
    compliance.py  ✓
        ↓
config.py        ← pathlib + pydantic-settings
        ↓
db.py            ← sqlite3 + schemas
        ↓
state_machine.py ← schemas/task.py only
        ↓
llm.py           ← anthropic/openai SDK + prompts/*.md
        ↓
services/        ← db + state_machine + llm + schemas
        ↓
cli.py           ← all services + rich
```

## Tool Usage

| Situation | Tool |
|-----------|------|
| After writing any `.py` file | `python -c "from harness.X import Y; print('OK')"` |
| After completing a phase | `/code-review` on changed files |
| Before marking phase gate | see `.claude/rules/phase-gates.md` |
| Service is complex | `/simplify` after first pass |
| Adding a new permission | `/update-config` skill |
| LLM prompt needs testing | Bash with real API key + inline Python |

## Current Phase

Phase 15 — Claude Code Syntax Executor Integration (complete)

All 15 phases complete. Build history: `.claude/rules/build-history.md`

## Agent Continuation

To resume building autonomously:

```
/loop Continue building the Harness project. Read CLAUDE.md Build Progress, find the first unchecked [ ] phase item, implement it per the plan at /home/fionn/.claude/plans/harness-complete-build-hashed-garden.md, run its GATE command (must pass green), mark [x] in CLAUDE.md, then continue to the next unchecked item. Never skip the GATE. Never auto-apply patches. Never commit without running pytest first.
```

Full loop instructions: `knowledge/AGENT_LOOP.md`
Detailed specs per phase: `/home/fionn/.claude/plans/harness-complete-build-hashed-garden.md`
Phase 15 spec: `plans/phase15_claude_code_integration.md`
Reference docs: `knowledge/`
