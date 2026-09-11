from __future__ import annotations

from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from uri_backend.errors import URIBackendError
from uri_backend.projects.models import (
    AuditEvent,
    MembershipCapability,
    Project,
    ProjectMembership,
    User,
)


class Capability(StrEnum):
    READ_PROJECT = "read_project"
    INGEST_SOURCE = "ingest_source"
    AUTHOR_DRAFT = "author_draft"
    REVIEW_DRAFT = "review_draft"
    PUBLISH_RECORD = "publish_record"
    MANAGE_MEMBERS = "manage_members"
    MANAGE_LIFECYCLE = "manage_lifecycle"
    EXPORT_PROJECT = "export_project"


ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    "owner": frozenset(Capability),
    "student_lead": frozenset(
        {
            Capability.READ_PROJECT,
            Capability.INGEST_SOURCE,
            Capability.AUTHOR_DRAFT,
            Capability.REVIEW_DRAFT,
            Capability.EXPORT_PROJECT,
        }
    ),
    "contributor": frozenset(
        {Capability.READ_PROJECT, Capability.INGEST_SOURCE, Capability.AUTHOR_DRAFT}
    ),
    "reviewer": frozenset({Capability.READ_PROJECT, Capability.REVIEW_DRAFT}),
    "guest": frozenset({Capability.READ_PROJECT}),
}


class UnknownActor(URIBackendError):
    pass


class CapabilityDenied(URIBackendError):
    pass


async def resolve_actor(session: AsyncSession, user_id: UUID) -> User:
    actor = await session.get(User, user_id)
    if actor is None:
        raise UnknownActor()
    return actor


async def require_capability(
    session: AsyncSession, user_id: UUID, project_id: UUID, capability: Capability
) -> ProjectMembership:
    membership = await session.scalar(
        sa.select(ProjectMembership).where(
            ProjectMembership.user_id == user_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.is_active.is_(True),
        )
    )
    if membership is None:
        raise CapabilityDenied()
    overrides = list(
        await session.scalars(
            sa.select(MembershipCapability.allowed).where(
                MembershipCapability.membership_id == membership.id,
                MembershipCapability.capability == capability.value,
            )
        )
    )
    if False in overrides:
        raise CapabilityDenied()
    if True in overrides or capability in ROLE_CAPABILITIES[membership.role]:
        return membership
    raise CapabilityDenied()


async def create_project(
    session: AsyncSession, actor: User, *, name: str, lab_id: UUID | None
) -> Project:
    project = Project(name=name, lab_id=lab_id)
    session.add(project)
    await session.flush()
    membership = ProjectMembership(
        user_id=actor.id, project_id=project.id, role="owner"
    )
    session.add(membership)
    session.add(
        AuditEvent(
            actor_id=actor.id,
            project_id=project.id,
            action="project.created",
            target_type="project",
            target_id=project.id,
            metadata_={"name": name},
        )
    )
    await session.flush()
    return project


async def add_member(
    session: AsyncSession, actor: User, project_id: UUID, user_id: UUID, role: str
) -> ProjectMembership:
    await require_capability(session, actor.id, project_id, Capability.MANAGE_MEMBERS)
    if await session.get(User, user_id) is None:
        raise UnknownActor()
    membership = await session.scalar(
        sa.select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user_id,
        )
    )
    if membership is None:
        membership = ProjectMembership(
            project_id=project_id, user_id=user_id, role=role
        )
        session.add(membership)
    else:
        membership.role = role
        membership.is_active = True
    await session.flush()
    session.add(
        AuditEvent(
            actor_id=actor.id,
            project_id=project_id,
            action="project.member_added",
            target_type="project_membership",
            target_id=membership.id,
            metadata_={"user_id": str(user_id), "role": role},
        )
    )
    await session.flush()
    return membership


async def readable_projects(session: AsyncSession, actor_id: UUID) -> list[Project]:
    memberships = await session.scalars(
        sa.select(ProjectMembership).where(
            ProjectMembership.user_id == actor_id, ProjectMembership.is_active.is_(True)
        )
    )
    readable_ids = []
    for membership in memberships:
        try:
            await require_capability(
                session, actor_id, membership.project_id, Capability.READ_PROJECT
            )
        except CapabilityDenied:
            continue
        readable_ids.append(membership.project_id)
    if not readable_ids:
        return []
    return list(
        (
            await session.scalars(
                sa.select(Project).where(Project.id.in_(readable_ids))
            )
        ).all()
    )
