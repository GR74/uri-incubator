from __future__ import annotations

from io import BytesIO
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from uri_backend.ingestion.adapters.git import (
    GIT_MANIFEST_MEDIA_TYPE,
    GitAdapter,
    InvalidGitRange,
    UnsafeSourcePath,
)
from uri_backend.projects.models import User
from uri_backend.projects.router import ActorDep, SessionDep
from uri_backend.projects.service import (
    Capability,
    CapabilityDenied,
    require_capability,
)
from uri_backend.sources.artifacts import LocalArtifactStore
from uri_backend.sources.models import ContentPart, Source, SourceVersion
from uri_backend.sources.schemas import (
    ContentPartResponse,
    GitPreviewResponse,
    GitRegistrationCommand,
    GitSourceCommand,
    RegisterSourceVersion,
    SourceResponse,
    SourceVersionResponse,
)
from uri_backend.sources.service import (
    ProjectReadOnly,
    register_source_version,
    require_writable_project,
)

router = APIRouter(prefix="/api", tags=["sources"])


def hide_unreadable(error: CapabilityDenied) -> HTTPException:
    return HTTPException(status_code=404, detail="Project not found.")


async def require_readable(
    session: AsyncSession, actor: User, project_id: UUID
) -> None:
    try:
        await require_capability(session, actor.id, project_id, Capability.READ_PROJECT)
    except CapabilityDenied as error:
        raise hide_unreadable(error) from error


def source_response(source: Source) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        project_id=source.project_id,
        family=source.family,
        external_id=source.external_id,
        title=source.title,
    )


def version_response(version: SourceVersion) -> SourceVersionResponse:
    return SourceVersionResponse(
        id=version.id,
        source_id=version.source_id,
        project_id=version.project_id,
        family=version.family,
        external_id=version.external_id,
        native_version=version.native_version,
        media_type=version.media_type,
        artifact_id=version.artifact_id,
    )


def git_preview_response(inventory) -> GitPreviewResponse:
    return GitPreviewResponse(
        resolved_head_sha=inventory.resolved_head_sha,
        commit_count=len(inventory.commits),
        allowed_file_count=len(inventory.files),
        excluded_file_count=len(inventory.exclusions),
        total_allowed_bytes=inventory.total_allowed_bytes,
        exclusions=inventory.exclusions,
    )


async def require_git_write(
    session: AsyncSession, actor: User, project_id: UUID
) -> None:
    try:
        await require_writable_project(session, actor, project_id)
    except ProjectReadOnly as error:
        raise HTTPException(
            status_code=409, detail="Stashed projects are read-only."
        ) from error


def inventory_git(command: GitSourceCommand):
    try:
        return GitAdapter().inventory(command)
    except (UnsafeSourcePath, InvalidGitRange) as error:
        raise HTTPException(
            status_code=422, detail="Unsafe or invalid Git source."
        ) from error


@router.post(
    "/projects/{project_id}/sources/git/preview", response_model=GitPreviewResponse
)
async def post_git_preview(
    project_id: UUID,
    command: GitSourceCommand,
    actor: ActorDep,
    session: SessionDep,
) -> GitPreviewResponse:
    await require_git_write(session, actor, project_id)
    return git_preview_response(inventory_git(command))


@router.post(
    "/projects/{project_id}/sources/git",
    response_model=SourceVersionResponse,
    status_code=201,
)
async def post_git_source(
    project_id: UUID,
    command: GitRegistrationCommand,
    request: Request,
    actor: ActorDep,
    session: SessionDep,
) -> SourceVersionResponse:
    await require_git_write(session, actor, project_id)
    adapter = GitAdapter()
    inventory = inventory_git(command)
    # Persist the canonical object manifest before registration/normalization so
    # future changes to the checkout cannot change this source version.
    stored = LocalArtifactStore(
        request.app.state.settings.artifact_root,
        request.app.state.settings.staging_root,
    ).put(BytesIO(adapter.manifest_bytes(inventory)))
    version = await register_source_version(
        session,
        actor,
        RegisterSourceVersion(
            project_id=project_id,
            family="git",
            external_id=str(inventory.repository_root),
            native_version=f"git:{command.start_commit}:{command.end_commit}:{inventory.resolved_head_sha}",
            media_type=GIT_MANIFEST_MEDIA_TYPE,
            title=command.title or inventory.repository_root.name,
            metadata={
                "resolved_head_sha": inventory.resolved_head_sha,
                "commit_count": len(inventory.commits),
                "allowed_file_count": len(inventory.files),
                "excluded_file_count": len(inventory.exclusions),
            },
        ),
        stored,
    )
    return version_response(version)


@router.post(
    "/projects/{project_id}/sources/uploads",
    response_model=SourceVersionResponse,
    status_code=201,
)
async def post_upload(
    project_id: UUID,
    request: Request,
    actor: ActorDep,
    session: SessionDep,
    family: Annotated[str, Query()],
    external_id: Annotated[str, Query()],
    native_version: Annotated[str, Query()],
    media_type: Annotated[str, Query()],
    title: Annotated[str | None, Query()] = None,
) -> SourceVersionResponse:
    settings = request.app.state.settings
    try:
        await require_writable_project(session, actor, project_id)
    except ProjectReadOnly as error:
        raise HTTPException(
            status_code=409, detail="Stashed projects are read-only."
        ) from error
    stored = await LocalArtifactStore(
        settings.artifact_root, settings.staging_root
    ).put_async(request.stream())
    command = RegisterSourceVersion(
        project_id=project_id,
        family=family,
        external_id=external_id,
        native_version=native_version,
        media_type=media_type,
        title=title,
    )
    try:
        version = await register_source_version(session, actor, command, stored)
    except ProjectReadOnly as error:
        raise HTTPException(
            status_code=409, detail="Stashed projects are read-only."
        ) from error
    return version_response(version)


@router.get("/projects/{project_id}/sources", response_model=list[SourceResponse])
async def get_sources(
    project_id: UUID, actor: ActorDep, session: SessionDep
) -> list[SourceResponse]:
    await require_readable(session, actor, project_id)
    sources = await session.scalars(
        sa.select(Source)
        .where(Source.project_id == project_id)
        .order_by(Source.created_at)
    )
    return [source_response(source) for source in sources]


@router.get("/projects/{project_id}/sources/{source_id}", response_model=SourceResponse)
async def get_source(
    project_id: UUID, source_id: UUID, actor: ActorDep, session: SessionDep
) -> SourceResponse:
    await require_readable(session, actor, project_id)
    source = await session.scalar(
        sa.select(Source).where(Source.id == source_id, Source.project_id == project_id)
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return source_response(source)


@router.get(
    "/projects/{project_id}/sources/{source_id}/versions",
    response_model=list[SourceVersionResponse],
)
async def get_versions(
    project_id: UUID, source_id: UUID, actor: ActorDep, session: SessionDep
) -> list[SourceVersionResponse]:
    await require_readable(session, actor, project_id)
    versions = await session.scalars(
        sa.select(SourceVersion)
        .where(
            SourceVersion.project_id == project_id, SourceVersion.source_id == source_id
        )
        .order_by(SourceVersion.created_at)
    )
    return [version_response(version) for version in versions]


@router.get(
    "/projects/{project_id}/source-versions/{version_id}/content",
    response_model=list[ContentPartResponse],
)
async def get_content(
    project_id: UUID, version_id: UUID, actor: ActorDep, session: SessionDep
) -> list[ContentPartResponse]:
    await require_readable(session, actor, project_id)
    version = await session.scalar(
        sa.select(SourceVersion).where(
            SourceVersion.id == version_id, SourceVersion.project_id == project_id
        )
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Source version not found.")
    parts = await session.scalars(
        sa.select(ContentPart)
        .where(ContentPart.source_version_id == version.id)
        .order_by(ContentPart.ordinal)
    )
    return [
        ContentPartResponse(
            id=part.id,
            ordinal=part.ordinal,
            kind=part.kind,
            text=part.text,
            locator=part.locator,
            author_label=part.author_label,
            source_time=part.source_time,
            metadata=part.metadata_,
        )
        for part in parts
    ]
