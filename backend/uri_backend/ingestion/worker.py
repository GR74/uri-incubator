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

    async def dispatch(self, job: ClaimedJob) -> None:
        handler = self._handlers.get(job.pipeline_version)
        if handler is None:
            raise LookupError(f"No handler registered for pipeline {job.pipeline_version!r}")
        await handler(job)


DEFAULT_DISPATCHER = PipelineDispatcher()


async def _complete_transition(
    sessions: async_sessionmaker[AsyncSession], job_id, worker_id: str
) -> None:
    async with sessions() as session:
        await complete_job(session, job_id, worker_id)
        await session.commit()


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
            async with sessions() as session:
                await fail_job(session, claimed.id, identity, "handler_error", "Worker handler failed")
                await session.commit()
        else:
            completion = asyncio.create_task(
                _complete_transition(sessions, claimed.id, identity)
            )
            try:
                await asyncio.shield(completion)
            except asyncio.CancelledError:
                await asyncio.shield(completion)
                raise


def main() -> None:
    engine = create_engine(Settings())
    try:
        asyncio.run(run_worker(session_factory(engine)))
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(engine.dispose())
