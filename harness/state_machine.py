from harness.schemas.task import TaskStatus

TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.INTAKE:                          {TaskStatus.INTERROGATING},
    TaskStatus.INTERROGATING:                   {TaskStatus.WAITING_FOR_DECISIONS},
    TaskStatus.WAITING_FOR_DECISIONS:           {TaskStatus.DECISIONS_APPROVED},
    TaskStatus.DECISIONS_APPROVED:              {TaskStatus.WAITING_FOR_CONTRACT_APPROVAL},
    TaskStatus.WAITING_FOR_CONTRACT_APPROVAL:   {TaskStatus.CONTRACT_READY, TaskStatus.DECISIONS_APPROVED},
    TaskStatus.CONTRACT_READY:                  {TaskStatus.WAITING_FOR_PATCH_APPROVAL},
    TaskStatus.WAITING_FOR_PATCH_APPROVAL:      {TaskStatus.IMPLEMENTING, TaskStatus.CONTRACT_READY},
    TaskStatus.IMPLEMENTING:                    {TaskStatus.CHECKING_COMPLIANCE},
    TaskStatus.CHECKING_COMPLIANCE:             {TaskStatus.VALIDATING, TaskStatus.IMPLEMENTING},
    TaskStatus.VALIDATING:                      {TaskStatus.DONE, TaskStatus.IMPLEMENTING},
    TaskStatus.DONE:                            set(),
}

COMMAND_REQUIRES: dict[str, set[TaskStatus]] = {
    "interrogate":       {TaskStatus.INTAKE},
    "answer":            {TaskStatus.WAITING_FOR_DECISIONS},
    "approve":           {TaskStatus.WAITING_FOR_DECISIONS},
    "contract":          {TaskStatus.DECISIONS_APPROVED},
    "contract_approve":  {TaskStatus.WAITING_FOR_CONTRACT_APPROVAL},
    "contract_reject":   {TaskStatus.WAITING_FOR_CONTRACT_APPROVAL},
    "implement":         {TaskStatus.CONTRACT_READY},
    "patch_approve":     {TaskStatus.WAITING_FOR_PATCH_APPROVAL},
    "patch_reject":      {TaskStatus.WAITING_FOR_PATCH_APPROVAL},
    "check":             {TaskStatus.IMPLEMENTING},
    "reimplement":       {TaskStatus.IMPLEMENTING},
    "validate":          {TaskStatus.CHECKING_COMPLIANCE, TaskStatus.VALIDATING},
    "remember":          {TaskStatus.DONE},
}


class InvalidTransitionError(Exception):
    def __init__(self, from_: TaskStatus, to: TaskStatus) -> None:
        valid = TRANSITIONS.get(from_, set())
        super().__init__(
            f"Cannot transition from {from_} to {to}.\n"
            f"Valid next states: {valid or 'none (terminal state)'}"
        )


class WrongStateError(Exception):
    def __init__(self, command: str, current: TaskStatus, required: set[TaskStatus]) -> None:
        super().__init__(
            f"Command '{command}' requires task to be in {required},\n"
            f"but current state is {current}."
        )


def validate_transition(from_: TaskStatus, to: TaskStatus) -> None:
    if to not in TRANSITIONS.get(from_, set()):
        raise InvalidTransitionError(from_, to)


def assert_command_allowed(command: str, current: TaskStatus) -> None:
    required = COMMAND_REQUIRES.get(command)
    if required and current not in required:
        raise WrongStateError(command, current, required)


def transition(task: dict, to: TaskStatus, db) -> None:
    from_status = TaskStatus(task["status"])
    validate_transition(from_status, to)
    db.update_task_status(task["id"], to.value)
    try:
        from harness.db import now_iso
        db.log_event({
            "id": db.new_event_id(),
            "task_id": task["id"],
            "event_type": "state_transition",
            "from_state": from_status.value,
            "to_state": to.value,
            "tool_name": None,
            "prompt_name": None,
            "input_hash": None,
            "output_hash": None,
            "duration_ms": None,
            "metadata_json": None,
            "created_at": now_iso(),
        })
    except Exception as _log_exc:
        import sys
        print(f"[harness] warning: failed to log event: {_log_exc}", file=sys.stderr)
