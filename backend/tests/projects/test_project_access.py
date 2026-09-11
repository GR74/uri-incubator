from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from uri_backend.api import create_app
from uri_backend.config import Settings
from uri_backend.projects.models import (
    MembershipCapability,
    Project,
    ProjectMembership,
    User,
)


@dataclass(frozen=True)
class SeededProject:
    id: UUID
    owner_id: UUID
    contributor_id: UUID
    reviewer_id: UUID


@pytest_asyncio.fixture(autouse=True)
async def clean_project_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "TRUNCATE TABLE audit_events, membership_capabilities, "
                "project_memberships, projects, labs, users CASCADE"
            )
        )


@pytest_asyncio.fixture
async def client(db_engine: AsyncEngine) -> httpx.AsyncClient:
    app = create_app(
        Settings(database_url="postgresql+psycopg://unused", pilot_mode=True)
    )
    app.state.database_engine = db_engine
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as result:
        yield result


@pytest_asyncio.fixture
async def seeded_project(db_engine: AsyncEngine) -> SeededProject:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    owner_id, contributor_id, reviewer_id = uuid4(), uuid4(), uuid4()
    project_id = uuid4()
    async with factory() as session:
        session.add_all(
            [
                User(id=owner_id, display_name="Owner", is_pilot_actor=True),
                User(
                    id=contributor_id, display_name="Contributor", is_pilot_actor=True
                ),
                User(id=reviewer_id, display_name="Reviewer", is_pilot_actor=True),
                Project(id=project_id, name="Access study"),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ProjectMembership(
                    user_id=owner_id, project_id=project_id, role="owner"
                ),
                ProjectMembership(
                    user_id=contributor_id, project_id=project_id, role="contributor"
                ),
            ]
        )
        await session.commit()
    return SeededProject(project_id, owner_id, contributor_id, reviewer_id)


async def test_contributor_cannot_manage_project_members(
    client: httpx.AsyncClient, seeded_project: SeededProject
) -> None:
    response = await client.post(
        f"/api/projects/{seeded_project.id}/members",
        headers={"X-URI-User-ID": str(seeded_project.contributor_id)},
        json={"user_id": str(seeded_project.reviewer_id), "role": "reviewer"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "capability_denied"


async def test_owner_can_manage_project_members(
    client: httpx.AsyncClient, seeded_project: SeededProject
) -> None:
    response = await client.post(
        f"/api/projects/{seeded_project.id}/members",
        headers={"X-URI-User-ID": str(seeded_project.owner_id)},
        json={"user_id": str(seeded_project.reviewer_id), "role": "reviewer"},
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == str(seeded_project.reviewer_id)
    assert response.json()["role"] == "reviewer"


async def test_explicit_capability_deny_overrides_owner_role(
    client: httpx.AsyncClient, db_engine: AsyncEngine, seeded_project: SeededProject
) -> None:
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        session.add(
            MembershipCapability(
                membership_id=(
                    await session.scalar(
                        sa.select(ProjectMembership.id).where(
                            ProjectMembership.user_id == seeded_project.owner_id,
                            ProjectMembership.project_id == seeded_project.id,
                        )
                    )
                ),
                capability="manage_members",
                allowed=False,
            )
        )
        await session.commit()

    response = await client.post(
        f"/api/projects/{seeded_project.id}/members",
        headers={"X-URI-User-ID": str(seeded_project.owner_id)},
        json={"user_id": str(seeded_project.reviewer_id), "role": "reviewer"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "capability_denied"


async def test_unknown_actor_and_inaccessible_project_are_not_disclosed(
    client: httpx.AsyncClient, seeded_project: SeededProject
) -> None:
    unknown = await client.get("/api/projects", headers={"X-URI-User-ID": str(uuid4())})
    inaccessible = await client.get(
        f"/api/projects/{seeded_project.id}",
        headers={"X-URI-User-ID": str(seeded_project.reviewer_id)},
    )

    assert unknown.status_code == 401
    assert unknown.json()["error"]["code"] == "unknown_actor"
    assert inaccessible.status_code == 404


async def test_pilot_actor_discovery_is_disabled_outside_pilot_mode(
    db_engine: AsyncEngine,
) -> None:
    app = create_app(
        Settings(database_url="postgresql+psycopg://unused", pilot_mode=False)
    )
    app.state.database_engine = db_engine
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as local_client:
        response = await local_client.get("/api/pilot/actors")

    assert response.status_code == 404


async def test_owner_project_creation_records_owner_membership_and_audit_event(
    client: httpx.AsyncClient, db_engine: AsyncEngine
) -> None:
    owner_id = uuid4()
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        session.add(User(id=owner_id, display_name="Creator", is_pilot_actor=True))
        await session.commit()

    response = await client.post(
        "/api/projects",
        headers={"X-URI-User-ID": str(owner_id)},
        json={"name": "New study"},
    )

    assert response.status_code == 201
    project_id = UUID(response.json()["id"])
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        owner = await session.scalar(
            sa.select(ProjectMembership).where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.user_id == owner_id,
            )
        )
        audit_count = await session.scalar(
            sa.text(
                "SELECT count(*) FROM audit_events WHERE project_id = :project_id AND actor_id = :actor_id"
            ),
            {"project_id": project_id, "actor_id": owner_id},
        )

    assert owner is not None
    assert owner.role == "owner"
    assert audit_count == 1
