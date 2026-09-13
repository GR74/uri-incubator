from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from uri_backend.api import create_app
from uri_backend.config import Settings
from uri_backend.projects.models import Project, ProjectMembership, User
from uri_backend.sources.artifacts import StoredArtifact
from uri_backend.sources.models import Artifact, Source, SourceVersion
from uri_backend.sources.schemas import RegisterSourceVersion
from uri_backend.sources.service import register_source_version


@dataclass(frozen=True)
class SourceFixture:
    project_id: UUID
    other_project_id: UUID
    actor_id: UUID
    outsider_id: UUID
    stashed_project_id: UUID


@pytest_asyncio.fixture(autouse=True)
async def clean_source_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "TRUNCATE TABLE source_quality_assessments, content_parts, source_versions, "
                "sources, artifacts, audit_events, membership_capabilities, "
                "project_memberships, projects, labs, users CASCADE"
            )
        )


@pytest_asyncio.fixture
async def source_fixture(db_engine: AsyncEngine) -> SourceFixture:
    actor_id, outsider_id = uuid4(), uuid4()
    project_id, other_project_id, stashed_project_id = uuid4(), uuid4(), uuid4()
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                User(id=actor_id, display_name="Researcher", is_pilot_actor=True),
                User(id=outsider_id, display_name="Outsider", is_pilot_actor=True),
                Project(id=project_id, name="Active project"),
                Project(id=other_project_id, name="Other active project"),
                Project(id=stashed_project_id, name="Archived", state="stashed"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ProjectMembership(
                    user_id=actor_id, project_id=project_id, role="owner"
                ),
                ProjectMembership(
                    user_id=actor_id, project_id=other_project_id, role="owner"
                ),
                ProjectMembership(
                    user_id=actor_id, project_id=stashed_project_id, role="owner"
                ),
            ]
        )
        await session.commit()
    return SourceFixture(
        project_id, other_project_id, actor_id, outsider_id, stashed_project_id
    )


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


def artifact() -> StoredArtifact:
    return StoredArtifact(
        sha256="1" * 64,
        storage_key="11/" + "1" * 62,
        byte_size=14,
    )


def git_status(root: Path) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
    ).stdout


def create_synthetic_git_repository(root: Path) -> str:
    root.mkdir()
    for args in (
        ("init", "--initial-branch=pilot"),
        ("config", "user.name", "Synthetic"),
        ("config", "user.email", "synthetic@example.test"),
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    (root / "methods.md").write_text("# synthetic methods\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "methods.md"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-m", "Synthetic methods"], check=True
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()


def approve_git_root(client: httpx.AsyncClient, project_id: UUID, root: Path) -> None:
    client._transport.app.state.settings.approved_git_repository_roots = {
        str(project_id): [root.resolve()]
    }


async def test_git_registration_excludes_secret_bytes_with_broad_paths(
    client, source_fixture, tmp_path
):
    """Secret exclusions must apply before immutable registration, not just preview display."""
    root = tmp_path / "secret-fixtures"
    create_synthetic_git_repository(root)
    for name in [
        ".env.local",
        ".env.production",
        "id_rsa",
        "certificate.pem",
        "access-token.json",
    ]:
        (root / name).write_text("REGISTRATION_SECRET_MARKER", encoding="utf-8")
    await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", str(root), "add", "."],
        check=True,
        capture_output=True,
    )
    await asyncio.to_thread(
        subprocess.run,
        ["git", "-C", str(root), "commit", "-m", "Add exclusions"],
        check=True,
        capture_output=True,
    )
    sha = (
        await asyncio.to_thread(
            subprocess.check_output,
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
        )
    ).strip()
    approve_git_root(client, source_fixture.project_id, root)
    response = await client.post(
        f"/api/projects/{source_fixture.project_id}/sources/git",
        headers={"X-URI-User-ID": str(source_fixture.actor_id)},
        json={
            "repository_root": str(root),
            "ref_name": "refs/heads/pilot",
            "start_commit": sha,
            "end_commit": sha,
            "include_paths": ["**"],
        },
    )
    assert response.status_code == 201
    artifacts = list((tmp_path / "artifacts").rglob("*"))
    assert any(path.is_file() for path in artifacts)
    assert all(
        b"REGISTRATION_SECRET_MARKER" not in path.read_bytes()
        for path in artifacts
        if path.is_file()
    )


async def test_same_source_version_is_idempotent(
    db_engine: AsyncEngine, source_fixture: SourceFixture
) -> None:
    command = RegisterSourceVersion(
        project_id=source_fixture.project_id,
        family="document",
        external_id="methods.md",
        native_version="git:abc123",
        media_type="text/markdown",
    )
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        actor = await session.get(User, source_fixture.actor_id)
        assert actor is not None
        first = await register_source_version(session, actor, command, artifact())
        second = await register_source_version(session, actor, command, artifact())
        await session.commit()

    assert first.id == second.id


async def test_concurrent_source_registration_returns_one_version(
    db_engine: AsyncEngine, source_fixture: SourceFixture
) -> None:
    """Two committing sessions must converge rather than leak a uniqueness error."""
    command = RegisterSourceVersion(
        project_id=source_fixture.project_id,
        family="document",
        external_id="race.md",
        native_version="git:abc123",
        media_type="text/markdown",
    )
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Artifact(**artifact().__dict__))
        session.add(
            Source(
                project_id=command.project_id,
                family=command.family,
                external_id=command.external_id,
            )
        )
        await session.commit()

    async def register_once() -> UUID:
        async with factory() as session:
            actor = await session.get(User, source_fixture.actor_id)
            assert actor is not None
            version = await register_source_version(session, actor, command, artifact())
            await session.commit()
            return version.id

    first_id, second_id = await asyncio.gather(register_once(), register_once())

    assert first_id == second_id


async def test_database_rejects_source_version_mutation(
    db_engine: AsyncEngine, source_fixture: SourceFixture
) -> None:
    """The append-only trigger must reject an update after registration."""
    command = RegisterSourceVersion(
        project_id=source_fixture.project_id,
        family="document",
        external_id="immutable.md",
        native_version="git:abc123",
        media_type="text/markdown",
    )
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        actor = await session.get(User, source_fixture.actor_id)
        assert actor is not None
        version = await register_source_version(session, actor, command, artifact())
        await session.commit()

    async with factory() as session:
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            await session.execute(
                sa.update(SourceVersion)
                .where(SourceVersion.id == version.id)
                .values(media_type="text/plain")
            )


async def test_path_traversal_external_id_never_shapes_artifact_storage(
    client: httpx.AsyncClient, source_fixture: SourceFixture, tmp_path: Path
) -> None:
    response = await client.post(
        f"/api/projects/{source_fixture.project_id}/sources/uploads",
        headers={"X-URI-User-ID": str(source_fixture.actor_id)},
        content=b"safe bytes",
        params={
            "family": "document",
            "external_id": "../../outside.md",
            "native_version": "git:abc123",
            "media_type": "text/markdown",
        },
    )

    assert response.status_code == 202
    assert not (tmp_path / "outside.md").exists()
    stored_files = [
        path for path in (tmp_path / "artifacts").rglob("*") if path.is_file()
    ]
    assert len(stored_files) == 1
    assert (
        stored_files[0].relative_to(tmp_path / "artifacts").as_posix().count("/") == 1
    )


async def test_cross_project_source_read_returns_not_found(
    client: httpx.AsyncClient, source_fixture: SourceFixture
) -> None:
    created = await client.post(
        f"/api/projects/{source_fixture.project_id}/sources/uploads",
        headers={"X-URI-User-ID": str(source_fixture.actor_id)},
        content=b"methods",
        params={
            "family": "document",
            "external_id": "methods.md",
            "native_version": "git:abc123",
            "media_type": "text/markdown",
        },
    )
    assert created.status_code == 202

    response = await client.get(
        f"/api/projects/{source_fixture.project_id}/sources",
        headers={"X-URI-User-ID": str(source_fixture.outsider_id)},
    )

    assert response.status_code == 404


async def test_stashed_project_rejects_source_upload(
    client: httpx.AsyncClient, source_fixture: SourceFixture, tmp_path: Path
) -> None:
    response = await client.post(
        f"/api/projects/{source_fixture.stashed_project_id}/sources/uploads",
        headers={"X-URI-User-ID": str(source_fixture.actor_id)},
        content=b"methods",
        params={
            "family": "document",
            "external_id": "methods.md",
            "native_version": "git:abc123",
            "media_type": "text/markdown",
        },
    )

    assert response.status_code == 409
    assert not (tmp_path / "artifacts").exists()


async def test_git_preview_is_authorized_and_does_not_persist(
    client: httpx.AsyncClient, source_fixture: SourceFixture, tmp_path: Path
) -> None:
    root = tmp_path / "synthetic-git"
    sha = create_synthetic_git_repository(root)
    approve_git_root(client, source_fixture.project_id, root)
    before = git_status(root)

    response = await client.post(
        f"/api/projects/{source_fixture.project_id}/sources/git/preview",
        headers={"X-URI-User-ID": str(source_fixture.actor_id)},
        json={
            "repository_root": str(root.resolve()),
            "ref_name": "refs/heads/pilot",
            "start_commit": sha,
            "end_commit": sha,
            "include_paths": ["methods.md"],
        },
    )

    after = git_status(root)
    assert response.status_code == 200
    assert response.json()["resolved_head_sha"] == sha
    assert response.json()["allowed_file_count"] == 1
    assert before == after == b""


async def test_git_registration_persists_an_immutable_manifest(
    client: httpx.AsyncClient, source_fixture: SourceFixture, tmp_path: Path
) -> None:
    root = tmp_path / "synthetic-git"
    sha = create_synthetic_git_repository(root)
    approve_git_root(client, source_fixture.project_id, root)

    response = await client.post(
        f"/api/projects/{source_fixture.project_id}/sources/git",
        headers={"X-URI-User-ID": str(source_fixture.actor_id)},
        json={
            "repository_root": str(root.resolve()),
            "ref_name": "refs/heads/pilot",
            "start_commit": sha,
            "end_commit": sha,
            "include_paths": ["methods.md"],
        },
    )

    assert response.status_code == 201
    assert response.json()["family"] == "git"
    artifacts = list((tmp_path / "artifacts").rglob("*"))
    manifest = next(path for path in artifacts if path.is_file()).read_text(
        encoding="ascii"
    )
    assert '"resolved_head_sha"' in manifest
    assert "synthetic methods" in manifest


async def test_git_preview_rejects_a_valid_but_unapproved_repository(
    client: httpx.AsyncClient, source_fixture: SourceFixture, tmp_path: Path
) -> None:
    root = tmp_path / "unapproved-git"
    sha = create_synthetic_git_repository(root)
    before = git_status(root)

    response = await client.post(
        f"/api/projects/{source_fixture.project_id}/sources/git/preview",
        headers={"X-URI-User-ID": str(source_fixture.actor_id)},
        json={
            "repository_root": str(root.resolve()),
            "ref_name": "refs/heads/pilot",
            "start_commit": sha,
            "end_commit": sha,
            "include_paths": ["methods.md"],
        },
    )

    assert response.status_code == 422
    assert git_status(root) == before == b""


async def test_git_approved_root_cannot_cross_project_boundary(
    client: httpx.AsyncClient, source_fixture: SourceFixture, tmp_path: Path
) -> None:
    root = tmp_path / "approved-for-first-project"
    sha = create_synthetic_git_repository(root)
    approve_git_root(client, source_fixture.project_id, root)

    response = await client.post(
        f"/api/projects/{source_fixture.other_project_id}/sources/git/preview",
        headers={"X-URI-User-ID": str(source_fixture.actor_id)},
        json={
            "repository_root": str(root.resolve()),
            "ref_name": "refs/heads/pilot",
            "start_commit": sha,
            "end_commit": sha,
            "include_paths": ["methods.md"],
        },
    )

    assert response.status_code == 422
