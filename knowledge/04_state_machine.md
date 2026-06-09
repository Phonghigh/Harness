# State Machine

9 states. Strict transition rules. No shortcuts.

## States

| State | Meaning | Active command |
|-------|---------|----------------|
| `INTAKE` | Task created, not yet interrogated | `harness interrogate` |
| `INTERROGATING` | LLM is generating decision map | (system-internal) |
| `WAITING_FOR_DECISIONS` | Decisions generated, awaiting human answers | `harness answer`, `harness approve` |
| `DECISIONS_APPROVED` | All decisions approved, ready for contract | `harness contract` |
| `CONTRACT_READY` | Contract created and approved | `harness implement` |
| `IMPLEMENTING` | Patch generated, ready for compliance check | `harness check` |
| `CHECKING_COMPLIANCE` | Compliance check running | (system-internal) |
| `VALIDATING` | Compliance passed, running build/tests | `harness validate` |
| `DONE` | All validation passed | `harness remember` |

## Transition Table

```
INTAKE                → INTERROGATING          (harness interrogate)
INTERROGATING         → WAITING_FOR_DECISIONS  (interrogator completes)
WAITING_FOR_DECISIONS → DECISIONS_APPROVED     (all decisions approved)
DECISIONS_APPROVED    → CONTRACT_READY         (harness contract)
CONTRACT_READY        → IMPLEMENTING           (harness implement)
IMPLEMENTING          → CHECKING_COMPLIANCE    (harness check)
CHECKING_COMPLIANCE   → VALIDATING             (compliance PASS)
CHECKING_COMPLIANCE   → IMPLEMENTING           (compliance FAIL — loop back)
VALIDATING            → DONE                   (harness validate — PASS)
VALIDATING            → IMPLEMENTING           (harness validate — FAIL — loop back)
DONE                  → (terminal)
```

## Forbidden Transitions

These must raise `InvalidTransitionError`, never silently proceed:

```
INTAKE                → IMPLEMENTING
INTAKE                → CONTRACT_READY
INTERROGATING         → IMPLEMENTING
WAITING_FOR_DECISIONS → IMPLEMENTING
WAITING_FOR_DECISIONS → CONTRACT_READY
DECISIONS_APPROVED    → IMPLEMENTING      (must create contract first)
ANY                   → DONE              (must go through VALIDATING)
```

## Command → Required State

```python
COMMAND_REQUIRES = {
    "interrogate":  {INTAKE},
    "answer":       {WAITING_FOR_DECISIONS},
    "approve":      {WAITING_FOR_DECISIONS},
    "contract":     {DECISIONS_APPROVED},
    "implement":    {CONTRACT_READY},
    "check":        {IMPLEMENTING},
    "validate":     {CHECKING_COMPLIANCE, VALIDATING},
    "remember":     {DONE},
}
```

If `current_status not in COMMAND_REQUIRES[command]`, raise `WrongStateError`.

## Implementation

```python
# state_machine.py

TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.INTAKE:                {TaskStatus.INTERROGATING},
    TaskStatus.INTERROGATING:         {TaskStatus.WAITING_FOR_DECISIONS},
    TaskStatus.WAITING_FOR_DECISIONS: {TaskStatus.DECISIONS_APPROVED},
    TaskStatus.DECISIONS_APPROVED:    {TaskStatus.CONTRACT_READY},
    TaskStatus.CONTRACT_READY:        {TaskStatus.IMPLEMENTING},
    TaskStatus.IMPLEMENTING:          {TaskStatus.CHECKING_COMPLIANCE},
    TaskStatus.CHECKING_COMPLIANCE:   {TaskStatus.VALIDATING, TaskStatus.IMPLEMENTING},
    TaskStatus.VALIDATING:            {TaskStatus.DONE, TaskStatus.IMPLEMENTING},
    TaskStatus.DONE:                  set(),
}

class InvalidTransitionError(Exception): ...
class WrongStateError(Exception): ...

def validate_transition(from_: TaskStatus, to: TaskStatus) -> None:
    if to not in TRANSITIONS.get(from_, set()):
        raise InvalidTransitionError(from_, to)

def assert_command_allowed(command: str, current: TaskStatus) -> None:
    required = COMMAND_REQUIRES.get(command)
    if required and current not in required:
        raise WrongStateError(command, current, required)

def transition(task: dict, to: TaskStatus, db) -> None:
    validate_transition(TaskStatus(task["status"]), to)
    db.update_task_status(task["id"], to.value)
```

## Error Messages

`InvalidTransitionError`:
```
Cannot transition from INTAKE to IMPLEMENTING.
Valid next states: {INTERROGATING}
```

`WrongStateError`:
```
Command 'implement' requires task to be in {CONTRACT_READY},
but current state is WAITING_FOR_DECISIONS.
Run 'harness decisions' and approve all pending decisions first.
```
