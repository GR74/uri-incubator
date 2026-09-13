import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import anyio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from uri_backend.config import Settings
from uri_backend.database import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest_asyncio.fixture
async def cli_environment(db_engine, test_database_url, tmp_path, monkeypatch):
    """Child processes are restricted to the migrated, isolated PostgreSQL fixture."""
    monkeypatch.setenv(
        "URI_DATABASE_URL",
        "postgresql+psycopg://development-must-not-be-used@127.0.0.1:1/development?connect_timeout=1",
    )
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("URI_")
    }
    environment.update(
        {
            "URI_DATABASE_URL": test_database_url,
            "URI_TEST_DATABASE_URL": test_database_url,
            "URI_ARTIFACT_ROOT": str(tmp_path / "artifacts"),
            "URI_STAGING_ROOT": str(tmp_path / "staging"),
        }
    )
    return environment


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def test_database_url() -> str:
    database_url = os.environ.get("URI_TEST_DATABASE_URL")
    if database_url is None:
        pytest.fail(
            "URI_TEST_DATABASE_URL is required for PostgreSQL integration tests; "
            "SQLite is not supported."
        )
    if not database_url.startswith("postgresql+psycopg://"):
        pytest.fail(
            "URI_TEST_DATABASE_URL must use postgresql+psycopg://; SQLite is not supported."
        )
    return database_url


@pytest_asyncio.fixture(scope="session")
async def db_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    result = await anyio.to_thread.run_sync(
        lambda: subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT,
            env={**os.environ, "URI_DATABASE_URL": test_database_url},
            check=False,
            capture_output=True,
            text=True,
        )
    )
    assert result.returncode == 0, result.stderr or result.stdout

    engine = create_engine(Settings(database_url=test_database_url))
    try:
        yield engine
    finally:
        await engine.dispose()
