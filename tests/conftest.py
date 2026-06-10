import pytest

from harness.config import HarnessConfig
from harness.db import Database, now_iso


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialize()
    return d


@pytest.fixture
def config():
    return HarnessConfig(
        project_name="test_project",
        llm_provider="anthropic",
        llm_model="claude-sonnet-4-6",
    )


@pytest.fixture
def task(db):
    from harness.services.task_service import create_task
    return create_task("Add user login with JWT", db)


@pytest.fixture
def mock_llm():
    from unittest.mock import MagicMock
    from harness.llm import LLMAdapter
    mock = MagicMock(spec=LLMAdapter)
    return mock
