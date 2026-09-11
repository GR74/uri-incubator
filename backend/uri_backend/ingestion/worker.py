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


async def unavailable_handler(_: ClaimedJob) -> None:
    raise RuntimeError("No ingestion handler is configured")


async def run_worker(sessions: async_sessionmaker[AsyncSession], handler: JobHandler = unavailable_handler, *, worker_id: str | None = None, poll_seconds: float = 1.0, lease_seconds: int = 30) -> None:
    """Process one committed database transition at a time until cancellation."""
    identity = worker_id or f"{socket.gethostname()}:{os.getpid()}"
    while True:
        async with sessions() as session:
            claimed = await claim_next_job(session, identity, lease_seconds)
            await session.commit()
        if claimed is None:
            await asyncio.sleep(poll_seconds)
            continue
        try:
            await handler(claimed)
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
            async with sessions() as session:
                await complete_job(session, claimed.id, identity)
                await session.commit()


def main() -> None:
    engine = create_engine(Settings())
    try:
        asyncio.run(run_worker(session_factory(engine)))
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(engine.dispose())
