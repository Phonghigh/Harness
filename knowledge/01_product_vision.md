# Product Vision

## What This Is

A **decision-first AI coding system** where:

- **Human** = Architect / Tech Lead / Decision Maker
- **AI** = Interrogator + Syntax Executor
- **System** = Workflow Controller + Memory + Compliance Gate

The AI does not convert requirements into code. It converts requirements into decisions. Only approved decisions are converted into an implementation contract. Only contracts are converted into code.

## What This Is Not

- Not a code-completion tool
- Not an AI pair programmer that makes choices
- Not a chat-based coding assistant
- Not an agent that "tries and fixes"

## Core Positioning

| Normal AI coding tools | This product |
|------------------------|--------------|
| Optimize for speed | Optimize for control |
| AI chooses architecture | Human chooses architecture |
| Requirement → Code | Requirement → Decisions → Contract → Code |
| Review after | Approve before |
| Black-box generation | Transparent decision trail |

**One-sentence pitch:**
> A decision-first AI coding control plane that forces AI to ask, record, and follow human-approved technical decisions before generating code.

## Target Users

**Primary:**
1. Junior to mid developers who want to learn deeply
2. Developers picking up a new stack
3. Tech leads who want AI for syntax but not architecture
4. Developers who have been burned by AI over-generating code

**Secondary:**
1. Engineering teams that want AI governance
2. Bootcamp students building real projects
3. Developers in regulated or security-sensitive systems

## Core Principle

```
The AI must never convert a requirement directly into code.
It must first convert the requirement into decisions.
Only approved decisions may be converted into syntax.
```

## What Breaks If This Is Violated

If AI writes code without approved decisions:
- Architecture choices become invisible
- Developer doesn't learn the reasoning
- Drift from project standards is undetected
- Compliance checking has nothing to compare against

If AI writes code without a contract:
- Scope is undefined → AI adds "helpful" features
- No allowed_files list → AI modifies wrong files
- No forbidden list → AI adds dependencies
