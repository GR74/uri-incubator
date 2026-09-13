from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest
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


@pytest.mark.parametrize(
    ("family", "media_type", "payload"),
    [
        (
            "reference_manifest",
            "application/json",
            b'{"records":[{"participant_id":"PRIVATE-MARKER-001","age":19}]}',
        ),
        (
            "notebook_run",
            "application/json",
            b'{"metrics":{"participant_id":"PRIVATE-MARKER-002","score":1}}',
        ),
    ],
)
async def test_generic_participant_rows_are_rejected_before_durable_storage(
    client: httpx.AsyncClient,
    pilot_owner: User,
    pilot_project: Project,
    family: str,
    media_type: str,
    payload: bytes,
) -> None:
    """Privacy-rejected upload bytes must never reach artifacts or PostgreSQL."""
    response = await client.post(
        f"/api/projects/{pilot_project.id}/sources/uploads",
        headers={"X-URI-User-ID": str(pilot_owner.id)},
        content=payload,
        params={
            "family": family,
            "external_id": "private-input.json",
            "native_version": "v1",
            "media_type": media_type,
        },
    )

    assert response.status_code == 422
    root = client._transport.app.state.settings.artifact_root.parent
    assert all(
        b"PRIVATE-MARKER" not in path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    )
    async with async_sessionmaker(client._transport.app.state.database_engine)() as session:
        assert await session.scalar(sa.text("SELECT count(*) FROM artifacts")) == 0
        assert await session.scalar(sa.text("SELECT count(*) FROM source_versions")) == 0
        assert await session.scalar(sa.text("SELECT count(*) FROM ingestion_runs")) == 0


@pytest.mark.parametrize(
    ("family", "media_type"),
    [("conversation", "application/json"), ("git", "application/json"), ("unknown", "text/plain")],
)
async def test_generic_upload_fails_closed_for_reserved_or_unknown_family(
    client: httpx.AsyncClient,
    pilot_owner: User,
    pilot_project: Project,
    family: str,
    media_type: str,
) -> None:
    response = await client.post(
        f"/api/projects/{pilot_project.id}/sources/uploads",
        headers={"X-URI-User-ID": str(pilot_owner.id)},
        content=b"PRIVATE-MARKER-RESERVED",
        params={
            "family": family,
            "external_id": "input",
            "native_version": "v1",
            "media_type": media_type,
        },
    )

    assert response.status_code == 422
    root = client._transport.app.state.settings.artifact_root.parent
    assert not any(path.is_file() for path in root.rglob("*"))


async def test_parse_failure_purges_generic_upload_quarantine(
    client: httpx.AsyncClient, pilot_owner: User, pilot_project: Project
) -> None:
    response = await client.post(
        f"/api/projects/{pilot_project.id}/sources/uploads",
        headers={"X-URI-User-ID": str(pilot_owner.id)},
        content=b"\xffPRIVATE-MARKER-PARSE",
        params={
            "family": "document",
            "external_id": "broken.md",
            "native_version": "v1",
            "media_type": "text/markdown",
        },
    )

    assert response.status_code == 422
    root = client._transport.app.state.settings.artifact_root.parent
    assert not any(path.is_file() for path in root.rglob("*"))


async def test_notebook_metadata_participant_row_is_purged_before_publication(
    client: httpx.AsyncClient, pilot_owner: User, pilot_project: Project
) -> None:
    marker = b"PRIVATE-NOTEBOOK-HTTP-MARKER"
    payload = (
        b'{"nbformat":4,"nbformat_minor":5,"metadata":{"records":[{"participant_id":"'
        + marker
        + b'","score":1}]},"cells":[]}'
    )
    response = await client.post(
        f"/api/projects/{pilot_project.id}/sources/uploads",
        headers={"X-URI-User-ID": str(pilot_owner.id)},
        content=payload,
        params={"family": "notebook_run", "external_id": "unsafe.ipynb", "native_version": "v1", "media_type": "application/x-ipynb+json"},
    )

    assert response.status_code == 422
    root = client._transport.app.state.settings.artifact_root.parent
    assert all(marker not in path.read_bytes() for path in root.rglob("*") if path.is_file())
    async with async_sessionmaker(client._transport.app.state.database_engine)() as session:
        for table in ("artifacts", "sources", "source_versions", "ingestion_runs"):
            assert await session.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0


async def test_interrupted_generic_upload_purges_quarantine(
    client: httpx.AsyncClient, pilot_owner: User, pilot_project: Project
) -> None:
    async def interrupted():
        yield b"PRIVATE-MARKER-INTERRUPTED"
        raise OSError("synthetic interrupted upload")

    with pytest.raises(OSError, match="synthetic interrupted upload"):
        await client.post(
            f"/api/projects/{pilot_project.id}/sources/uploads",
            headers={"X-URI-User-ID": str(pilot_owner.id)},
            content=interrupted(),
            params={
                "family": "document",
                "external_id": "interrupted.md",
                "native_version": "v1",
                "media_type": "text/markdown",
            },
        )

    root = client._transport.app.state.settings.artifact_root.parent
    assert not any(path.is_file() for path in root.rglob("*"))


@pytest.mark.parametrize(
    ("family", "media_type", "payload"),
    [
        ("notebook_run", "application/json", b'{"metrics":{"accuracy":0}}'),
        (
            "reference_manifest",
            "application/json",
            b'{"accession":"synthetic-accession","cohort_summary":{"n":10}}',
        ),
        (
            "lab_notebook",
            "application/json",
            b'{"entry_id":"synthetic-entry","sections":[{"text":"Calibrated instrument."}]}',
        ),
    ],
)
async def test_valid_generic_source_publishes_one_version_and_queue(
    client: httpx.AsyncClient,
    pilot_owner: User,
    pilot_project: Project,
    family: str,
    media_type: str,
    payload: bytes,
) -> None:
    response = await client.post(
        f"/api/projects/{pilot_project.id}/sources/uploads",
        headers={"X-URI-User-ID": str(pilot_owner.id)},
        content=payload,
        params={
            "family": family,
            "external_id": f"{family}.json",
            "native_version": "v1",
            "media_type": media_type,
        },
    )

    assert response.status_code == 202
    async with async_sessionmaker(client._transport.app.state.database_engine)() as session:
        assert await session.scalar(
            sa.text("SELECT count(*) FROM source_versions")
        ) == 1
        assert await session.scalar(sa.text("SELECT count(*) FROM ingestion_runs")) == 1
