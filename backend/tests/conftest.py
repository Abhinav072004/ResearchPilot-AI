import os
from tempfile import TemporaryDirectory

import pytest

scratch = TemporaryDirectory(prefix="researchpilot-test-")
os.environ.setdefault("RP_DATABASE_URL", f"sqlite:///{scratch.name}/test.db")
os.environ.setdefault("RP_LOCAL_OBJECTS", f"{scratch.name}/objects")

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, local_rates


@pytest.fixture(scope="session", autouse=True)
def migrate():
    command.upgrade(Config("alembic.ini"), "head")
    if settings().database_url.startswith("postgresql"):
        from agents.supervisor import checkpointer
        with checkpointer() as saver:
            saver.setup()


@pytest.fixture(autouse=True)
def isolate_request_quota():
    local_rates.clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
