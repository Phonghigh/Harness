import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class HarnessConfig(BaseModel):
    project_name: str
    llm_provider: str
    llm_model: str
    validate_commands: list[str] = []
    max_tokens: Annotated[int, Field(ge=1)] = 4096
    llm_retries: Annotated[int, Field(ge=1)] = 3


class EnvSettings(BaseSettings):
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    harness_provider: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


def find_harness_root(start: Path | None = None) -> Path | None:
    current = start or Path.cwd()
    while True:
        candidate = current / ".harness" / "config.json"
        if candidate.exists():
            return current / ".harness"
        parent = current.parent
        if parent == current:
            return None
        current = parent


def load_config() -> tuple[Path, HarnessConfig]:
    harness_dir = find_harness_root()
    if harness_dir is None:
        raise typer.BadParameter(
            "Not a harness project. Run 'harness init' first."
        )
    data = json.loads((harness_dir / "config.json").read_text())
    return harness_dir, HarnessConfig.model_validate(data)


def save_config(harness_dir: Path, config: HarnessConfig) -> None:
    (harness_dir / "config.json").write_text(config.model_dump_json(indent=2))
