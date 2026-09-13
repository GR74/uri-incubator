from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from uri_backend.ingestion.models import IngestionJob, IngestionJobAttempt, IngestionRun

MAX_ERROR_DETAIL = 1000
SAFE_ERROR_DETAILS = frozenset({"Worker lease expired", "Worker handler failed"})
SAFE_ERROR_CODES = frozenset(
    {"cancelled", "handler_error", "lease_expired", "parse_error"}
)


class JobLeaseLost(Exception):
    """The job is no longer owned by the requesting worker."""


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    run_id: UUID
    attempt: int
    pipeline_version: str
    worker_id: str = ""


def _bounded_detail(detail: str | None) -> str | None:
    if detail is None:
        return None
    normalized = detail.strip()[:MAX_ERROR_DETAIL]
    if normalized in SAFE_ERROR_DETAILS:
        return normalized
    return "Error detail redacted"


def _safe_error_code(code: str) -> str:
    return code if code in SAFE_ERROR_CODES else "internal_error"


async def enqueue_ingestion(
    session: AsyncSession, source_version_id: UUID, idempotency_key: str
) -> IngestionRun:
    run_id = await session.scalar(
        pg_insert(IngestionRun)
        .values(
            source_version_id=source_version_id,
            pipeline_version=idempotency_key,
            idempotency_key=idempotency_key,
            status="queued",
        )
        .on_conflict_do_nothing(constraint="uq_ingestion_run_source_pipeline")
        .returning(IngestionRun.id)
    )
    if run_id is None:
        run_id = await session.scalar(
            sa.select(IngestionRun.id).where(
                IngestionRun.source_version_id == source_version_id,
                IngestionRun.pipeline_version == idempotency_key,
            )
        )
    assert run_id is not None
    await session.execute(
        pg_insert(IngestionJob)
        .values(run_id=run_id, status="queued")
        .on_conflict_do_nothing(index_elements=[IngestionJob.run_id])
    )
    run = await session.get(IngestionRun, run_id)
    assert run is not None
    return run


async def claim_next_job(
    session: AsyncSession,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int | None = None,
) -> ClaimedJob | None:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    now = sa.func.now()
    while terminal := await session.scalar(
        sa.select(IngestionJob)
        .where(
            IngestionJob.status == "running",
            IngestionJob.lease_expires_at <= now,
            IngestionJob.attempt >= IngestionJob.max_attempts,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    ):
        await _finish_attempt(
            session, terminal, "lease_expired", "lease_expired", "Worker lease expired"
        )
        terminal.status = "failed"
        terminal.completed_at = now
        terminal.error_code = "lease_expired"
        terminal.error_detail = "Worker lease expired"
        run = await session.get(IngestionRun, terminal.run_id)
        assert run is not None
        run.status, run.completed_at = "failed", now
        run.error_code, run.error_detail = "lease_expired", "Worker lease expired"
    candidate = await session.scalar(
        sa.select(IngestionJob)
        .where(
            sa.or_(
                sa.and_(
                    IngestionJob.status == "queued", IngestionJob.available_at <= now
                ),
                sa.and_(
                    IngestionJob.status == "running",
                    IngestionJob.lease_expires_at <= now,
                    IngestionJob.attempt < IngestionJob.max_attempts,
                ),
            )
        )
        .order_by(IngestionJob.available_at, IngestionJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if candidate is None:
        return None
    if candidate.attempt == 0 and max_attempts is not None:
        candidate.max_attempts = max_attempts
    if candidate.status == "running":
        await _finish_attempt(
            session, candidate, "lease_expired", "lease_expired", "Worker lease expired"
        )
    candidate.status, candidate.worker_id = "running", worker_id
    candidate.attempt += 1
    candidate.heartbeat_at, candidate.lease_expires_at = (
        now,
        now + timedelta(seconds=lease_seconds),
    )
    candidate.error_code, candidate.error_detail = None, None
    run = await session.get(IngestionRun, candidate.run_id)
    assert run is not None
    run.status, run.error_code, run.error_detail = "running", None, None
    session.add(
        IngestionJobAttempt(
            job_id=candidate.id, attempt=candidate.attempt, worker_id=worker_id
        )
    )
    await session.flush()
    return ClaimedJob(
        candidate.id,
        candidate.run_id,
        candidate.attempt,
        run.pipeline_version,
        worker_id,
    )


async def release_job(session: AsyncSession, claimed: ClaimedJob) -> None:
    """Return interrupted work to the queue; shutdown is not job cancellation."""
    job = await owned_claim(session, claimed)
    await _finish_attempt(session, job, "retry")
    job.status, job.worker_id, job.lease_expires_at = "queued", None, None
    job.available_at = sa.func.now()
    # A shutdown should not consume the final retry allowance.
    job.max_attempts = max(job.max_attempts, job.attempt + 1)
    run = await session.get(IngestionRun, job.run_id)
    run.status = "queued"
    await session.flush()


async def owned_claim(session: AsyncSession, claimed: ClaimedJob) -> IngestionJob:
    job = await session.scalar(
        sa.select(IngestionJob)
        .where(
            IngestionJob.id == claimed.id,
            IngestionJob.run_id == claimed.run_id,
            IngestionJob.attempt == claimed.attempt,
            IngestionJob.worker_id == claimed.worker_id,
            IngestionJob.status == "running",
            IngestionJob.lease_expires_at > sa.func.clock_timestamp(),
        )
        .with_for_update()
    )
    if job is None:
        raise JobLeaseLost("job lease is no longer owned by this worker")
    return job


async def _owned_job(
    session: AsyncSession, job_id: UUID, worker_id: str
) -> IngestionJob:
    job = await session.scalar(
        sa.select(IngestionJob)
        .where(
            IngestionJob.id == job_id,
            IngestionJob.status == "running",
            IngestionJob.worker_id == worker_id,
            IngestionJob.lease_expires_at > sa.func.now(),
        )
        .with_for_update()
    )
    if job is None:
        raise JobLeaseLost("job lease is no longer owned by this worker")
    return job


async def _finish_attempt(
    session: AsyncSession,
    job: IngestionJob,
    outcome: str,
    code: str | None = None,
    detail: str | None = None,
) -> None:
    attempt = await session.scalar(
        sa.select(IngestionJobAttempt)
        .where(
            IngestionJobAttempt.job_id == job.id,
            IngestionJobAttempt.attempt == job.attempt,
        )
        .with_for_update()
    )
    assert attempt is not None
    attempt.finished_at, attempt.outcome = sa.func.now(), outcome
    attempt.error_code, attempt.error_detail = code, _bounded_detail(detail)


async def heartbeat_job(
    session: AsyncSession, job_id: UUID, worker_id: str, lease_seconds: int
) -> IngestionJob:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    job, now = await _owned_job(session, job_id, worker_id), sa.func.now()
    job.heartbeat_at, job.lease_expires_at = now, now + timedelta(seconds=lease_seconds)
    await session.flush()
    return job


async def complete_job(
    session: AsyncSession, job_id: UUID, worker_id: str
) -> IngestionJob:
    job, now = await _owned_job(session, job_id, worker_id), sa.func.now()
    await _finish_attempt(session, job, "succeeded")
    job.status, job.completed_at, job.lease_expires_at = "succeeded", now, None
    run = await session.get(IngestionRun, job.run_id)
    assert run is not None
    run.status, run.completed_at = "succeeded", now
    await session.flush()
    return job


async def fail_job(
    session: AsyncSession,
    job_id: UUID,
    worker_id: str,
    error_code: str,
    error_detail: str | None = None,
) -> IngestionJob:
    job, now, detail = (
        await _owned_job(session, job_id, worker_id),
        sa.func.now(),
        _bounded_detail(error_detail),
    )
    safe_code = _safe_error_code(error_code)
    terminal = job.attempt >= job.max_attempts
    await _finish_attempt(
        session, job, "failed" if terminal else "retry", safe_code, detail
    )
    job.error_code, job.error_detail, job.lease_expires_at, job.worker_id = (
        safe_code,
        detail,
        None,
        None,
    )
    job.status = "failed" if terminal else "queued"
    if terminal:
        job.completed_at = now
    else:
        job.available_at = now
    run = await session.get(IngestionRun, job.run_id)
    assert run is not None
    run.status, run.error_code, run.error_detail = job.status, job.error_code, detail
    if terminal:
        run.completed_at = now
    await session.flush()
    return job


async def cancel_job(
    session: AsyncSession, job_id: UUID, worker_id: str
) -> IngestionJob:
    job, now = await _owned_job(session, job_id, worker_id), sa.func.now()
    await _finish_attempt(session, job, "cancelled")
    job.status, job.completed_at, job.lease_expires_at = "cancelled", now, None
    run = await session.get(IngestionRun, job.run_id)
    assert run is not None
    run.status, run.completed_at = "cancelled", now
    await session.flush()
    return job
