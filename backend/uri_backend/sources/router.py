from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uri_backend.ingestion.adapters.conversations import (
    ConversationService,
    ConversationStageError,
    StageExpired,
    UnknownConversation,
    promote_selected_conversations,
)
from uri_backend.ingestion.adapters.git import (
    GIT_MANIFEST_MEDIA_TYPE,
    GitAdapter,
    InvalidGitRange,
    UnsafeSourcePath,
)
from uri_backend.ingestion.models import IngestionRun
from uri_backend.projects.models import Project, User
from uri_backend.projects.router import ActorDep, SessionDep
from uri_backend.projects.service import (
    Capability,
    CapabilityDenied,
    require_capability,
)
from uri_backend.sources.artifacts import LocalArtifactStore
from uri_backend.sources.models import (
    ContentPart,
    Source,
    SourceQualityAssessment,
    SourceVersion,
)
from uri_backend.sources.schemas import (
    ContentPartResponse,
    ConversationPreviewResponse,
    ConversationSelectionCommand,
    GitPreviewResponse,
    GitRegistrationCommand,
    GitSourceCommand,
    IngestionAcceptedResponse,
    IngestionStatusResponse,
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


def conversation_service(
    request: Request, actor: User, project_id: UUID
) -> ConversationService:
    services = getattr(request.app.state, "conversation_services", None)
    if services is None:
        services = {}
        request.app.state.conversation_services = services
    key = (actor.id, project_id)
    service = services.get(key)
    if service is None:
        settings = request.app.state.settings
        service = ConversationService(
            async_sessionmaker(
                request.app.state.database_engine, expire_on_commit=False
            ),
            LocalArtifactStore(settings.artifact_root, settings.staging_root),
            settings.staging_root / "conversation-exports",
            actor.id,
            project_id,
        )
        services[key] = service
    return service


def conversation_preview_response(inventory) -> ConversationPreviewResponse:
    return ConversationPreviewResponse(
        stage_id=inventory.stage_id,
        conversations=[
            item.model_dump(mode="json") for item in inventory.conversations
        ],
        expires_at=inventory.expires_at,
    )


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


def ingestion_accepted_response(version: SourceVersion) -> IngestionAcceptedResponse:
    return IngestionAcceptedResponse(
        **version_response(version).model_dump(),
        status_url=f"/api/projects/{version.project_id}/source-versions/{version.id}/ingestion",
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


def require_approved_git_root(
    request: Request, project_id: UUID, command: GitSourceCommand
) -> None:
    """Fail closed before Git is invoked unless this project owns the exact root."""
    submitted = command.repository_root
    try:
        canonical = submitted.resolve(strict=True)
    except OSError as error:
        raise HTTPException(
            status_code=422, detail="Unsafe or unapproved Git source."
        ) from error
    approved_roots = request.app.state.settings.approved_git_repository_roots.get(
        str(project_id), []
    )
    if submitted != canonical or not approved_roots:
        raise HTTPException(status_code=422, detail="Unsafe or unapproved Git source.")
    for approved in approved_roots:
        try:
            if (
                approved.is_absolute()
                and approved == approved.resolve(strict=True)
                and canonical == approved
            ):
                return
        except OSError:
            continue
    raise HTTPException(status_code=422, detail="Unsafe or unapproved Git source.")


@router.post(
    "/projects/{project_id}/sources/git/preview", response_model=GitPreviewResponse
)
async def post_git_preview(
    project_id: UUID,
    command: GitSourceCommand,
    request: Request,
    actor: ActorDep,
    session: SessionDep,
) -> GitPreviewResponse:
    await require_git_write(session, actor, project_id)
    require_approved_git_root(request, project_id, command)
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
    require_approved_git_root(request, project_id, command)
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
            native_version=(
                f"git:{inventory.commits[0].sha}:{inventory.commits[-1].sha}:"
                f"{inventory.resolved_head_sha}"
            ),
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
    "/projects/{project_id}/sources/conversations/preview",
    response_model=ConversationPreviewResponse,
    status_code=201,
)
async def post_conversation_preview(
    project_id: UUID,
    request: Request,
    actor: ActorDep,
    session: SessionDep,
) -> ConversationPreviewResponse:
    await require_git_write(session, actor, project_id)
    try:
        inventory = await conversation_service(
            request, actor, project_id
        ).inventory_async(request.stream(), timedelta(minutes=15))
    except ConversationStageError as error:
        raise HTTPException(
            status_code=422, detail="Conversation export could not be staged."
        ) from error
    return conversation_preview_response(inventory)


@router.post(
    "/projects/{project_id}/sources/conversations/{stage_id}/promote",
    response_model=list[SourceVersionResponse],
    status_code=201,
)
async def post_conversation_promotion(
    project_id: UUID,
    stage_id: str,
    command: ConversationSelectionCommand,
    request: Request,
    actor: ActorDep,
    session: SessionDep,
) -> list[SourceVersionResponse]:
    await require_git_write(session, actor, project_id)
    try:
        project = await session.get(Project, project_id)
        if project is None:
            raise UnknownConversation("Conversation project was not found.")
        versions = await promote_selected_conversations(
            stage_id,
            command.conversation_ids,
            actor,
            project,
            service=conversation_service(request, actor, project_id),
        )
    except StageExpired as error:
        raise HTTPException(
            status_code=410, detail="Conversation stage has expired."
        ) from error
    except (UnknownConversation, ConversationStageError) as error:
        raise HTTPException(
            status_code=422, detail="Conversation stage could not be promoted."
        ) from error
    return [version_response(version) for version in versions]


@router.delete(
    "/projects/{project_id}/sources/conversations/{stage_id}",
    status_code=204,
    response_model=None,
)
async def delete_conversation_stage(
    project_id: UUID,
    stage_id: str,
    request: Request,
    actor: ActorDep,
    session: SessionDep,
) -> None:
    await require_git_write(session, actor, project_id)
    try:
        conversation_service(request, actor, project_id).cancel(stage_id)
    except ConversationStageError as error:
        raise HTTPException(
            status_code=500, detail="Conversation stage purge failed."
        ) from error


@router.post(
    "/projects/{project_id}/sources/uploads",
    response_model=IngestionAcceptedResponse,
    status_code=202,
)
async def post_upload(
    project_id: UUID,
    request: Request,
    actor: ActorDep,
    session: SessionDep,
    family: Annotated[str | None, Query()] = None,
    external_id: Annotated[str | None, Query()] = None,
    native_version: Annotated[str | None, Query()] = None,
    media_type: Annotated[str | None, Query()] = None,
    title: Annotated[str | None, Query()] = None,
) -> IngestionAcceptedResponse:
    settings = request.app.state.settings
    try:
        await require_writable_project(session, actor, project_id)
    except ProjectReadOnly as error:
        raise HTTPException(
            status_code=409, detail="Stashed projects are read-only."
        ) from error
    stream = request.stream()
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=422, detail="A source file is required.")
        family = str(form.get("family") or "")
        external_id = str(form.get("external_id") or "")
        native_version = str(form.get("native_version") or "")
        title = str(form.get("title")) if form.get("title") is not None else title
        media_type = str(getattr(upload, "content_type", "") or media_type or "")

        async def stream_upload():
            while chunk := await upload.read(1024 * 1024):
                yield chunk

        stream = stream_upload()
    if not family or not external_id or not native_version or not media_type:
        raise HTTPException(
            status_code=422,
            detail="Source family, identity, version, and media type are required.",
        )
    stored = await LocalArtifactStore(
        settings.artifact_root, settings.staging_root
    ).put_async(stream)
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
    return ingestion_accepted_response(version)


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


@router.get(
    "/projects/{project_id}/source-versions/{version_id}/ingestion",
    response_model=IngestionStatusResponse,
)
async def get_ingestion_status(
    project_id: UUID, version_id: UUID, actor: ActorDep, session: SessionDep
) -> IngestionStatusResponse:
    """Return only project-authorized operational progress and completed outputs."""
    await require_readable(session, actor, project_id)
    run = await session.scalar(
        sa.select(IngestionRun)
        .join(SourceVersion, IngestionRun.source_version_id == SourceVersion.id)
        .where(SourceVersion.project_id == project_id, SourceVersion.id == version_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Ingestion run not found.")
    part_count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ContentPart)
        .where(ContentPart.source_version_id == version_id)
    )
    assessment = await session.scalar(
        sa.select(SourceQualityAssessment).where(
            SourceQualityAssessment.source_version_id == version_id
        )
    )
    quality = None
    if assessment is not None:
        quality = {
            "dimensions": assessment.dimensions,
            "warnings": assessment.warnings,
            "overall_score": None,
        }
    return IngestionStatusResponse(
        id=run.id,
        source_version_id=version_id,
        status=run.status,
        error_code=run.error_code,
        error_detail=run.error_detail,
        part_count=part_count or 0,
        quality=quality,
    )
