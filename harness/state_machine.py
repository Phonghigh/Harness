from harness.schemas.task import TaskStatus

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

COMMAND_REQUIRES: dict[str, set[TaskStatus]] = {
    "interrogate": {TaskStatus.INTAKE},
    "answer":      {TaskStatus.WAITING_FOR_DECISIONS},
    "approve":     {TaskStatus.WAITING_FOR_DECISIONS},
    "contract":    {TaskStatus.DECISIONS_APPROVED},
    "implement":   {TaskStatus.CONTRACT_READY},
    "check":       {TaskStatus.IMPLEMENTING},
    "validate":    {TaskStatus.CHECKING_COMPLIANCE, TaskStatus.VALIDATING},
    "remember":    {TaskStatus.DONE},
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
    validate_transition(TaskStatus(task["status"]), to)
    db.update_task_status(task["id"], to.value)
