from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from uri_backend.projects.models import AuditEvent, Project, User
from uri_backend.projects.service import Capability, require_capability
from uri_backend.sources.artifacts import StoredArtifact
from uri_backend.sources.models import Artifact, Source, SourceVersion
from uri_backend.sources.schemas import RegisterSourceVersion


class ProjectReadOnly(Exception):
    """Raised before any source write to a stashed project."""


async def require_writable_project(
    session: AsyncSession, actor: User, project_id: UUID
) -> None:
    await require_capability(session, actor.id, project_id, Capability.INGEST_SOURCE)
    project = await session.get(Project, project_id)
    if project is None or project.state == "stashed":
        raise ProjectReadOnly()


async def register_source_version(
    session: AsyncSession,
    actor: User,
    command: RegisterSourceVersion,
    artifact: StoredArtifact,
) -> SourceVersion:
    await require_writable_project(session, actor, command.project_id)

    db_artifact = await session.scalar(
        sa.select(Artifact).where(Artifact.sha256 == artifact.sha256)
    )
    if db_artifact is None:
        db_artifact = Artifact(
            sha256=artifact.sha256,
            storage_key=artifact.storage_key,
            byte_size=artifact.byte_size,
        )
        session.add(db_artifact)
        await session.flush()

    existing = await session.scalar(
        sa.select(SourceVersion).where(
            SourceVersion.project_id == command.project_id,
            SourceVersion.family == command.family,
            SourceVersion.external_id == command.external_id,
            SourceVersion.native_version == command.native_version,
            SourceVersion.artifact_id == db_artifact.id,
        )
    )
    if existing is not None:
        return existing

    source = await session.scalar(
        sa.select(Source).where(
            Source.project_id == command.project_id,
            Source.family == command.family,
            Source.external_id == command.external_id,
        )
    )
    if source is None:
        source = Source(
            project_id=command.project_id,
            family=command.family,
            external_id=command.external_id,
            title=command.title,
        )
        session.add(source)
        await session.flush()

    version = SourceVersion(
        source_id=source.id,
        project_id=command.project_id,
        artifact_id=db_artifact.id,
        family=command.family,
        external_id=command.external_id,
        native_version=command.native_version,
        media_type=command.media_type,
        metadata_=command.metadata,
        created_by=actor.id,
    )
    session.add(version)
    await session.flush()
    session.add(
        AuditEvent(
            actor_id=actor.id,
            project_id=command.project_id,
            action="source.version_registered",
            target_type="source_version",
            target_id=version.id,
            metadata_={"source_id": str(source.id), "artifact_id": str(db_artifact.id)},
        )
    )
    await session.flush()
    return version
