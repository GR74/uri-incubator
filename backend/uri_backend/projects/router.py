from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uri_backend.projects.models import Project, ProjectMembership, User
from uri_backend.projects.schemas import (
    MembershipCreate,
    MembershipResponse,
    PilotActorResponse,
    ProjectCreate,
    ProjectResponse,
)
from uri_backend.projects.service import (
    Capability,
    CapabilityDenied,
    add_member,
    create_project,
    readable_projects,
    require_capability,
    resolve_actor,
)

router = APIRouter(prefix="/api", tags=["projects"])


async def session_for_request(request: Request) -> AsyncIterator[AsyncSession]:
    engine = request.app.state.database_engine
    if engine is None:
        raise RuntimeError("Database is unavailable.")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


async def actor_for_request(
    x_uri_user_id: Annotated[UUID, Header(alias="X-URI-User-ID")],
    session: Annotated[AsyncSession, Depends(session_for_request)],
) -> User:
    return await resolve_actor(session, x_uri_user_id)


def project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id, name=project.name, state=project.state, lab_id=project.lab_id
    )


def membership_response(membership: ProjectMembership) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        user_id=membership.user_id,
        project_id=membership.project_id,
        role=membership.role,
        is_active=membership.is_active,
    )


SessionDep = Annotated[AsyncSession, Depends(session_for_request)]
ActorDep = Annotated[User, Depends(actor_for_request)]


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def post_project(
    command: ProjectCreate,
    actor: ActorDep,
    session: SessionDep,
) -> ProjectResponse:
    return project_response(
        await create_project(session, actor, name=command.name, lab_id=command.lab_id)
    )


@router.get("/projects", response_model=list[ProjectResponse])
async def get_projects(actor: ActorDep, session: SessionDep) -> list[ProjectResponse]:
    return [
        project_response(project)
        for project in await readable_projects(session, actor.id)
    ]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    actor: ActorDep,
    session: SessionDep,
) -> ProjectResponse:
    try:
        await require_capability(session, actor.id, project_id, Capability.READ_PROJECT)
    except CapabilityDenied as error:
        raise HTTPException(status_code=404, detail="Project not found.") from error
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project_response(project)


@router.post(
    "/projects/{project_id}/members", response_model=MembershipResponse, status_code=201
)
async def post_project_member(
    project_id: UUID,
    command: MembershipCreate,
    actor: ActorDep,
    session: SessionDep,
) -> MembershipResponse:
    return membership_response(
        await add_member(session, actor, project_id, command.user_id, command.role)
    )


@router.get("/pilot/actors", response_model=list[PilotActorResponse])
async def get_pilot_actors(
    request: Request, session: SessionDep
) -> list[PilotActorResponse]:
    if not request.app.state.settings.pilot_mode:
        raise HTTPException(status_code=404, detail="Not found.")
    actors = await session.scalars(sa.select(User).where(User.is_pilot_actor.is_(True)))
    return [
        PilotActorResponse(id=actor.id, display_name=actor.display_name)
        for actor in actors
    ]
