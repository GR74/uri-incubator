from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uri_backend.config import Settings
from uri_backend.database import create_engine, session_factory
from uri_backend.ingestion.queue import (
    ClaimedJob,
    cancel_job,
    claim_next_job,
    complete_job,
    fail_job,
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
            raise LookupError(f"No handler registered for pipeline {job.pipeline_version!r}")
        await handler(job)


DEFAULT_DISPATCHER = PipelineDispatcher()


class WorkerConfigurationError(RuntimeError):
    """Raised before polling when no pipeline handler is installed."""


def build_default_dispatcher() -> PipelineDispatcher:
    """Compose installed pipeline handlers; Task 6 adds normalization registration here."""
    return PipelineDispatcher()


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
        await fail_job(session, job_id, worker_id, "handler_error", "Worker handler failed")
        await session.commit()


async def _await_committed(transition: Awaitable[None]) -> None:
    task = asyncio.create_task(transition)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.shield(task)
        raise


async def run_worker(sessions: async_sessionmaker[AsyncSession], dispatcher: PipelineDispatcher | None = None, *, worker_id: str | None = None, poll_seconds: float = 1.0, lease_seconds: int = 30) -> None:
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
    sessions: async_sessionmaker[AsyncSession], dispatcher: PipelineDispatcher | None = None
) -> None:
    active_dispatcher = dispatcher or build_default_dispatcher()
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
