import typer

from harness.db import Database, now_iso
from harness.schemas.task import TaskStatus


def create_task(requirement: str, db: Database) -> dict:
    if db.get_active_task() is not None:
        active = db.get_active_task()
        raise typer.BadParameter(
            f"Active task {active['id']} exists (status: {active['status']}). Complete it first."
        )
    task_id = Database.new_task_id()
    now = now_iso()
    task = {
        "id": task_id,
        "title": requirement[:80],
        "raw_requirement": requirement,
        "status": TaskStatus.INTAKE,
        "created_at": now,
        "updated_at": now,
    }
    db.create_task(task)
    return dict(db.get_task(task_id))


def get_active_task_or_exit(db: Database) -> dict:
    task = db.get_active_task()
    if task is None:
        typer.echo("Error: No active task. Run 'harness start \"requirement\"' first.", err=True)
        raise typer.Exit(1)
    return dict(task)
