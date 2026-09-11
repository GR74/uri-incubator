from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from uri_backend.api import create_app
from uri_backend.config import Settings
from uri_backend.ingestion.worker import run_one_worker_job
from uri_backend.projects.models import Project, ProjectMembership, User


@pytest_asyncio.fixture(autouse=True)
async def clean_ingestion_api_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "TRUNCATE TABLE ingestion_job_attempts, ingestion_jobs, ingestion_runs, "
                "source_quality_assessments, content_parts, source_versions, sources, artifacts, "
                "audit_events, membership_capabilities, project_memberships, projects, labs, users CASCADE"
            )
        )


@pytest_asyncio.fixture
async def pilot_owner(db_engine: AsyncEngine) -> User:
    owner = User(id=uuid4(), display_name="Synthetic owner", is_pilot_actor=True)
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        session.add(owner)
        await session.commit()
    return owner


@pytest_asyncio.fixture
async def pilot_project(db_engine: AsyncEngine, pilot_owner: User) -> Project:
    project = Project(id=uuid4(), name="Synthetic ingestion project")
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                project,
                ProjectMembership(
                    user_id=pilot_owner.id, project_id=project.id, role="owner"
                ),
            ]
        )
        await session.commit()
    return project


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine, tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        Settings(
            database_url="postgresql+psycopg://unused",
            pilot_mode=True,
            artifact_root=tmp_path / "artifacts",
            staging_root=tmp_path / "staging",
        )
    )
    app.state.database_engine = db_engine
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as result:
        yield result


async def test_uploaded_markdown_reaches_normalized_terminal_state(
    client: httpx.AsyncClient, pilot_owner: User, pilot_project: Project
) -> None:
    """Skipping the dispatcher transaction would leave an accepted upload without parts or quality."""
    created = await client.post(
        f"/api/projects/{pilot_project.id}/sources/uploads",
        headers={"X-URI-User-ID": str(pilot_owner.id), "Idempotency-Key": "methods-v1"},
        files={
            "file": (
                "methods.md",
                b"# Method\n\nUse the reviewed pipeline.",
                "text/markdown",
            )
        },
        data={
            "family": "document",
            "external_id": "methods.md",
            "native_version": "pilot-v1",
        },
    )
    assert created.status_code == 202
    await run_one_worker_job(
        async_sessionmaker(
            client._transport.app.state.database_engine, expire_on_commit=False
        ),
        artifact_root=client._transport.app.state.settings.artifact_root,
    )
    status = await client.get(
        created.json()["status_url"], headers={"X-URI-User-ID": str(pilot_owner.id)}
    )
    assert status.json()["status"] == "succeeded"
    assert status.json()["part_count"] == 2
    assert status.json()["quality"]["overall_score"] is None
