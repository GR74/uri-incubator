from __future__ import annotations

import asyncio
import os
import signal
import socket
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uri_backend.config import Settings
from uri_backend.database import create_engine, session_factory
from uri_backend.ingestion.adapters import (
    AdapterRegistry,
    ConversationAdapter,
    DocumentAdapter,
    GitAdapter,
    LabNotebookAdapter,
    ManifestAdapter,
    NotebookAdapter,
)
from uri_backend.ingestion.contracts import AdapterInput
from uri_backend.ingestion.models import IngestionRun
from uri_backend.ingestion.quality import (
    SourceContext,
    assess_source,
    safe_parser_warnings,
)
from uri_backend.ingestion.queue import (
    ClaimedJob,
    JobLeaseLost,
    claim_next_job,
    complete_job,
    enqueue_extraction,
    fail_job,
    heartbeat_job,
    owned_claim,
    release_job,
)
from uri_backend.knowledge.extraction import ExtractionConfig, extract_candidates
from uri_backend.retrieval.providers import (
    StructuredGenerationProvider,
    build_model_provider,
)
from uri_backend.sources.models import (
    Artifact,
    ContentPart,
    SourceQualityAssessment,
    SourceVersion,
)

JobHandler = Callable[[ClaimedJob], Awaitable[None]]


class PipelineDispatcher:
    """Explicit registry boundary for pipeline-specific workers added by later tasks."""

    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, pipeline_version: str, handler: JobHandler) -> None:
        if not pipeline_version:
            raise ValueError("pipeline_version is required")
        self._handlers[pipeline_version] = handler

    def can_dispatch(self, pipeline_version: str) -> bool:
        return pipeline_version in self._handlers

    @property
    def has_handlers(self) -> bool:
        return bool(self._handlers)

    async def dispatch(self, job: ClaimedJob) -> None:
        handler = self._handlers.get(job.pipeline_version)
        if handler is None:
            raise LookupError(
                f"No handler registered for pipeline {job.pipeline_version!r}"
            )
        await handler(job)


DEFAULT_DISPATCHER = PipelineDispatcher()


class WorkerConfigurationError(RuntimeError):
    """Raised before polling when no pipeline handler is installed."""


def default_adapter_registry() -> AdapterRegistry:
    return AdapterRegistry(
        [
            ConversationAdapter(),
            DocumentAdapter(),
            GitAdapter(),
            NotebookAdapter(),
            ManifestAdapter(),
            LabNotebookAdapter(),
        ]
    )


def build_normalization_handler(
    sessions: async_sessionmaker[AsyncSession] | None,
    artifact_root: Path | None = None,
    registry: AdapterRegistry | None = None,
) -> JobHandler:
    """Build the durable document-normalization handler used by the CLI worker."""
    adapters = registry or default_adapter_registry()

    async def handler(job: ClaimedJob) -> None:
        if sessions is None:
            raise WorkerConfigurationError(
                "Normalization handler requires database sessions"
            )
        await persist_normalization(
            sessions, job, artifact_root or Settings().artifact_root, adapters
        )

    return handler


def _configured_extraction_config(settings: Settings) -> ExtractionConfig:
    return ExtractionConfig(
        model_id=settings.generation_model or "unconfigured",
        model_digest=settings.generation_model_digest or "unavailable",
        prompt_version="extraction-prompt-v1",
        schema_version="candidate-batch-v1",
        parser_version="normalization-v1",
        sampling_config={"temperature": 0},
        sampling_version="sampling-v1",
    )


def build_extraction_handler(
    sessions: async_sessionmaker[AsyncSession] | None,
    provider: StructuredGenerationProvider | None = None,
    extraction_config: ExtractionConfig | None = None,
) -> JobHandler:
    """Build a fenced extraction handler; completion remains the worker's job."""
    settings = Settings()
    active_provider = provider or build_model_provider(settings)
    active_config = extraction_config or _configured_extraction_config(settings)

    async def handler(job: ClaimedJob) -> None:
        if sessions is None:
            raise WorkerConfigurationError("Extraction handler requires database sessions")
        async with sessions() as session:
            source_version_id = await session.scalar(
                sa.select(IngestionRun.source_version_id).where(IngestionRun.id == job.run_id)
            )
            if source_version_id is None:
                raise LookupError(f"Unknown ingestion run {job.run_id}")
            await session.commit()
            await extract_candidates(
                session,
                source_version_id,
                active_provider,
                active_config,
                ingestion_run_id=job.run_id,
                claimed_job=job,
            )

    return handler


async def persist_normalization(
    sessions: async_sessionmaker[AsyncSession],
    job: ClaimedJob,
    artifact_root: Path,
    registry: AdapterRegistry,
) -> None:
    """Normalize one claimed artifact and publish its complete part set atomically."""
    async with sessions() as session, session.begin():
        record = (
            await session.execute(
                sa.select(IngestionRun, SourceVersion, Artifact)
                .join(SourceVersion, IngestionRun.source_version_id == SourceVersion.id)
                .join(Artifact, SourceVersion.artifact_id == Artifact.id)
                .where(IngestionRun.id == job.run_id)
            )
        ).one_or_none()
        if record is None:
            raise LookupError(f"Unknown ingestion run {job.run_id}")
        _, version, artifact = record
        artifact_path = _artifact_path(artifact_root, artifact.storage_key)
        adapter = registry.resolve(version.family, version.media_type)
        context = AdapterInput(
            artifact_path=artifact_path,
            media_type=version.media_type,
            family=version.family,
            metadata=version.metadata_,
        )
        version_id, native_version = version.id, version.native_version
    # Parsing cannot hold locks or block the heartbeat event loop.
    result = await asyncio.to_thread(adapter.normalize, context)
    async with sessions() as session, session.begin():
        await owned_claim(session, job)
        await session.execute(
            sa.select(IngestionRun)
            .where(IngestionRun.id == job.run_id)
            .with_for_update()
        )
        await session.execute(
            sa.text("SELECT set_config('uri.ingestion_run_id', :run_id, true)"),
            {"run_id": str(job.run_id)},
        )
        await session.execute(
            sa.delete(ContentPart).where(
                ContentPart.source_version_id == version_id,
                ContentPart.metadata_["ingestion_run_id"].astext == str(job.run_id),
            )
        )
        if result.status == "failed":
            raise ValueError("Document normalization failed")
        if result.status == "unsupported":
            raise LookupError("Unsupported source adapter")
        report = assess_source(
            SourceContext(
                family=context.family,
                has_author=any(part.author_label is not None for part in result.parts),
                has_source_time=any(
                    part.source_time is not None for part in result.parts
                ),
                has_native_version=bool(native_version),
                has_reproducibility_links=bool(
                    context.metadata.get("reproducibility_links")
                ),
            ),
            result,
        )
        session.add_all(
            [
                ContentPart(
                    source_version_id=version_id,
                    ordinal=part.ordinal,
                    kind=part.kind,
                    text=part.text,
                    locator=part.locator,
                    author_label=part.author_label,
                    source_time=part.source_time,
                    metadata_={**part.metadata, "ingestion_run_id": str(job.run_id)},
                )
                for part in result.parts
            ]
        )
        assessment_id = await session.scalar(
            pg_insert(SourceQualityAssessment)
            .values(
                source_version_id=version_id,
                normalization={
                    "status": result.status,
                    "adapter": result.adapter
                    if result.adapter
                    in {
                        "document",
                        "git",
                        "conversation",
                        "notebook_run",
                        "reference_manifest",
                        "lab_notebook",
                    }
                    else "unknown",
                    "adapter_version": result.adapter_version
                    if result.adapter_version == "normalization-v1"
                    else "unknown",
                    "parse_coverage": result.parse_coverage,
                },
                dimensions={
                    name: dimension.model_dump()
                    for name, dimension in report.dimensions.items()
                },
                warnings=safe_parser_warnings(result)
                + [
                    {"category": "privacy", "message": warning}
                    for warning in report.privacy_warnings
                ]
                + [
                    {"category": "licensing", "message": warning}
                    for warning in report.licensing_warnings
                ],
            )
            .on_conflict_do_nothing(constraint="uq_source_quality_assessment_version")
            .returning(SourceQualityAssessment.id)
        )
        if assessment_id is None:
            assessment_id = await session.scalar(
                sa.select(SourceQualityAssessment.id).where(
                    SourceQualityAssessment.source_version_id == version_id
                )
            )
        assert assessment_id is not None
        await session.flush()
        # This job becomes durable with the normalized parts. A crash cannot
        # create extraction work for a version whose normalization rolled back.
        await enqueue_extraction(session, version_id)
        # Check wall-clock lease validity again after potentially slow writes.
        await owned_claim(session, job)


async def run_one_worker_job(
    sessions: async_sessionmaker[AsyncSession],
    *,
    artifact_root: Path | None = None,
    worker_id: str = "test-worker",
) -> bool:
    """Process one queued job for bounded integration and smoke checks."""
    async with sessions() as session:
        claimed = await claim_next_job(session, worker_id, lease_seconds=30)
        await session.commit()
    if claimed is None:
        return False
    try:
        await build_normalization_handler(sessions, artifact_root)(claimed)
    except Exception:
        await _failure_transition(sessions, claimed)
        raise
    await _complete_transition(sessions, claimed)
    return True


def _artifact_path(artifact_root: Path, storage_key: str) -> Path:
    root = artifact_root.resolve()
    path = (root / storage_key).resolve()
    if root not in path.parents:
        raise ValueError("Artifact storage key escapes the configured root")
    return path


def build_default_dispatcher(
    sessions: async_sessionmaker[AsyncSession] | None = None,
    artifact_root: Path | None = None,
) -> PipelineDispatcher:
    """Compose installed pipeline handlers."""
    dispatcher = PipelineDispatcher()
    dispatcher.register(
        "normalization-v1", build_normalization_handler(sessions, artifact_root)
    )
    dispatcher.register("extraction-v1", build_extraction_handler(sessions))
    return dispatcher


async def _complete_transition(
    sessions: async_sessionmaker[AsyncSession], claimed: ClaimedJob
) -> None:
    async with sessions() as session:
        await owned_claim(session, claimed)
        await complete_job(session, claimed.id, claimed.worker_id)
        await session.commit()


async def _failure_transition(
    sessions: async_sessionmaker[AsyncSession], claimed: ClaimedJob, *, retryable: bool = True
) -> None:
    async with sessions() as session:
        await owned_claim(session, claimed)
        await fail_job(
            session,
            claimed.id,
            claimed.worker_id,
            "handler_error",
            "Worker handler failed",
            terminal=not retryable,
        )
        await session.commit()


async def _await_committed(transition: Awaitable[None]) -> None:
    task = asyncio.create_task(transition)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(task)
        finally:
            raise asyncio.CancelledError


async def _release_transition(sessions, claimed):
    async with sessions() as session:
        try:
            await release_job(session, claimed)
            await session.commit()
        except JobLeaseLost:
            await session.rollback()


async def _renew_lease(sessions, claimed, lease_seconds, heartbeat_seconds):
    while True:
        await asyncio.sleep(heartbeat_seconds)
        async with sessions() as session:
            try:
                await owned_claim(session, claimed)
                await heartbeat_job(
                    session, claimed.id, claimed.worker_id, lease_seconds
                )
                await session.commit()
            except JobLeaseLost:
                return


async def run_worker(
    sessions: async_sessionmaker[AsyncSession],
    dispatcher: PipelineDispatcher | None = None,
    *,
    worker_id: str | None = None,
    poll_seconds: float = 1.0,
    lease_seconds: int = 30,
    heartbeat_seconds: float | None = None,
    max_attempts: int | None = None,
) -> None:
    """Process one committed database transition at a time until cancellation."""
    identity = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    active_dispatcher = dispatcher or DEFAULT_DISPATCHER
    if heartbeat_seconds is not None and not 0 < heartbeat_seconds < lease_seconds:
        raise WorkerConfigurationError(
            "Heartbeat interval must be shorter than the lease"
        )
    while True:
        async with sessions() as session:
            claimed = await claim_next_job(
                session, identity, lease_seconds, max_attempts
            )
            await session.commit()
        if claimed is None:
            await asyncio.sleep(poll_seconds)
            continue
        heartbeat = asyncio.create_task(
            _renew_lease(
                sessions,
                claimed,
                lease_seconds,
                heartbeat_seconds or lease_seconds / 3,
            )
        )
        try:
            try:
                await active_dispatcher.dispatch(claimed)
            except asyncio.CancelledError:
                await _await_committed(_release_transition(sessions, claimed))
                raise
            except JobLeaseLost:
                continue
            except Exception as error:  # noqa: BLE001 - durable, redacted handler outcome.
                await _await_committed(
                    _failure_transition(sessions, claimed, retryable=getattr(error, "retryable", True))
                )
            else:
                await _await_committed(_complete_transition(sessions, claimed))
        except JobLeaseLost:
            pass
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)


async def run_configured_worker(
    sessions: async_sessionmaker[AsyncSession],
    dispatcher: PipelineDispatcher | None = None,
) -> None:
    settings = Settings()
    active_dispatcher = dispatcher or build_default_dispatcher(
        sessions, settings.artifact_root
    )
    if not active_dispatcher.has_handlers:
        raise WorkerConfigurationError("No ingestion pipeline handlers are installed")
    await run_worker(
        sessions,
        dispatcher=active_dispatcher,
        poll_seconds=settings.job_poll_interval_seconds,
        lease_seconds=settings.job_lease_seconds,
        heartbeat_seconds=settings.job_heartbeat_interval_seconds,
        max_attempts=settings.job_max_attempts,
    )


def main() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def serve() -> None:
        engine = create_engine(Settings())
        task = asyncio.create_task(run_configured_worker(session_factory(engine)))
        loop = asyncio.get_running_loop()
        previous = {}

        def stop(signum, frame):
            # Repeated signals must not interrupt the protected outcome commit.
            if not task.cancelling():
                loop.call_soon_threadsafe(task.cancel)

        for signum in (
            signal.SIGINT,
            signal.SIGTERM,
            *([signal.SIGBREAK] if sys.platform == "win32" else []),
        ):
            previous[signum] = signal.signal(signum, stop)
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            await engine.dispose()

    asyncio.run(serve())
