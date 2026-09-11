from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from uri_backend.ingestion.queue import enqueue_ingestion
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

    with session.no_autoflush:
        artifact_id = await session.scalar(
            pg_insert(Artifact)
            .values(
                sha256=artifact.sha256,
                storage_key=artifact.storage_key,
                byte_size=artifact.byte_size,
            )
            .on_conflict_do_nothing(index_elements=[Artifact.sha256])
            .returning(Artifact.id)
        )
        if artifact_id is None:
            artifact_id = await session.scalar(
                sa.select(Artifact.id).where(Artifact.sha256 == artifact.sha256)
            )
        assert artifact_id is not None

        source_id = await session.scalar(
            pg_insert(Source)
            .values(
                project_id=command.project_id,
                family=command.family,
                external_id=command.external_id,
                title=command.title,
            )
            .on_conflict_do_nothing(constraint="uq_source_project_identity")
            .returning(Source.id)
        )
        if source_id is None:
            source_id = await session.scalar(
                sa.select(Source.id).where(
                    Source.project_id == command.project_id,
                    Source.family == command.family,
                    Source.external_id == command.external_id,
                )
            )
        assert source_id is not None

        version_id = await session.scalar(
            pg_insert(SourceVersion)
            .values(
                source_id=source_id,
                project_id=command.project_id,
                artifact_id=artifact_id,
                family=command.family,
                external_id=command.external_id,
                native_version=command.native_version,
                media_type=command.media_type,
                metadata_=command.metadata,
                created_by=actor.id,
            )
            .on_conflict_do_nothing(constraint="uq_source_version_idempotency")
            .returning(SourceVersion.id)
        )
        if version_id is None:
            version_id = await session.scalar(
                sa.select(SourceVersion.id).where(
                    SourceVersion.project_id == command.project_id,
                    SourceVersion.family == command.family,
                    SourceVersion.external_id == command.external_id,
                    SourceVersion.native_version == command.native_version,
                    SourceVersion.artifact_id == artifact_id,
                )
            )
            assert version_id is not None
        else:
            session.add(
                AuditEvent(
                    actor_id=actor.id,
                    project_id=command.project_id,
                    action="source.version_registered",
                    target_type="source_version",
                    target_id=version_id,
                    metadata_={"source_id": str(source_id), "artifact_id": str(artifact_id)},
                )
            )
    version = await session.get(SourceVersion, version_id)
    assert version is not None
    await enqueue_ingestion(session, version.id, "normalization-v1")
    return version
