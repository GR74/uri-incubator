from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uri_backend.config import Settings
from uri_backend.database import create_engine, session_factory
from uri_backend.ingestion.adapters import (
    AdapterRegistry,
    DocumentAdapter,
    GitAdapter,
    LabNotebookAdapter,
    ManifestAdapter,
    NotebookAdapter,
)
from uri_backend.ingestion.contracts import AdapterInput
from uri_backend.ingestion.models import IngestionRun
from uri_backend.ingestion.queue import (
    ClaimedJob,
    cancel_job,
    claim_next_job,
    complete_job,
    fail_job,
)
from uri_backend.sources.models import Artifact, ContentPart, SourceVersion

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
    return AdapterRegistry([DocumentAdapter(), GitAdapter(), NotebookAdapter(), ManifestAdapter(), LabNotebookAdapter()])


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
                .with_for_update()
            )
        ).one_or_none()
        if record is None:
            raise LookupError(f"Unknown ingestion run {job.run_id}")
        _, version, artifact = record
        await session.execute(
            sa.text("SELECT set_config('uri.ingestion_run_id', :run_id, true)"),
            {"run_id": str(job.run_id)},
        )
        await session.execute(
            sa.delete(ContentPart).where(
                ContentPart.source_version_id == version.id,
                ContentPart.metadata_["ingestion_run_id"].astext == str(job.run_id),
            )
        )
        artifact_path = _artifact_path(artifact_root, artifact.storage_key)
        adapter = registry.resolve(version.family, version.media_type)
        result = adapter.normalize(
            AdapterInput(
                artifact_path=artifact_path,
                media_type=version.media_type,
                family=version.family,
                metadata=version.metadata_,
            )
        )
        if result.status == "failed":
            raise ValueError("Document normalization failed")
        if result.status == "unsupported":
            raise LookupError("Unsupported source adapter")
        session.add_all(
            [
                ContentPart(
                    source_version_id=version.id,
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
    return dispatcher


async def _complete_transition(
    sessions: async_sessionmaker[AsyncSession], job_id, worker_id: str
) -> None:
    async with sessions() as session:
        await complete_job(session, job_id, worker_id)
        await session.commit()


async def _failure_transition(
    sessions: async_sessionmaker[AsyncSession], job_id, worker_id: str
) -> None:
    async with sessions() as session:
        await fail_job(
            session, job_id, worker_id, "handler_error", "Worker handler failed"
        )
        await session.commit()


async def _await_committed(transition: Awaitable[None]) -> None:
    task = asyncio.create_task(transition)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.shield(task)
        raise


async def run_worker(
    sessions: async_sessionmaker[AsyncSession],
    dispatcher: PipelineDispatcher | None = None,
    *,
    worker_id: str | None = None,
    poll_seconds: float = 1.0,
    lease_seconds: int = 30,
) -> None:
    """Process one committed database transition at a time until cancellation."""
    identity = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    active_dispatcher = dispatcher or DEFAULT_DISPATCHER
    while True:
        async with sessions() as session:
            claimed = await claim_next_job(session, identity, lease_seconds)
            await session.commit()
        if claimed is None:
            await asyncio.sleep(poll_seconds)
            continue
        try:
            await active_dispatcher.dispatch(claimed)
        except asyncio.CancelledError:
            async with sessions() as session:
                await cancel_job(session, claimed.id, identity)
                await session.commit()
            raise
        except Exception:  # noqa: BLE001 - handler failures become durable job outcomes.
            await _await_committed(_failure_transition(sessions, claimed.id, identity))
        else:
            await _await_committed(_complete_transition(sessions, claimed.id, identity))


async def run_configured_worker(
    sessions: async_sessionmaker[AsyncSession],
    dispatcher: PipelineDispatcher | None = None,
) -> None:
    active_dispatcher = dispatcher or build_default_dispatcher(sessions)
    if not active_dispatcher.has_handlers:
        raise WorkerConfigurationError("No ingestion pipeline handlers are installed")
    await run_worker(sessions, dispatcher=active_dispatcher)


def main() -> None:
    engine = create_engine(Settings())
    try:
        asyncio.run(run_configured_worker(session_factory(engine)))
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(engine.dispose())
