from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from uri_backend.ingestion.models import IngestionJob, IngestionRun
from uri_backend.ingestion.queue import (
    JobLeaseLost,
    cancel_job,
    claim_next_job,
    complete_job,
    enqueue_ingestion,
    fail_job,
    heartbeat_job,
)
from uri_backend.projects.models import Project, ProjectMembership, User
from uri_backend.sources.models import Artifact, Source, SourceVersion


@pytest_asyncio.fixture(autouse=True)
async def clean_ingestion_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "TRUNCATE TABLE ingestion_job_attempts, ingestion_jobs, ingestion_runs, "
                "source_quality_assessments, content_parts, source_versions, sources, artifacts, "
                "audit_events, membership_capabilities, project_memberships, projects, labs, users CASCADE"
            )
        )


@pytest_asyncio.fixture
async def source_version_id(db_engine: AsyncEngine) -> UUID:
    project_id, user_id, source_id, artifact_id, version_id = (uuid4() for _ in range(5))
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                User(id=user_id, display_name="Queue tester", is_pilot_actor=True),
                Project(id=project_id, name="Queue project"),
                Artifact(id=artifact_id, sha256="2" * 64, storage_key="22/" + "2" * 62, byte_size=1),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ProjectMembership(user_id=user_id, project_id=project_id, role="owner"),
                Source(id=source_id, project_id=project_id, family="document", external_id="queue.md"),
            ]
        )
        await session.flush()
        session.add(
            SourceVersion(
                id=version_id,
                source_id=source_id,
                project_id=project_id,
                artifact_id=artifact_id,
                family="document",
                external_id="queue.md",
                native_version="v1",
                media_type="text/markdown",
                created_by=user_id,
            )
        )
        await session.commit()
    return version_id


async def enqueue(db_engine: AsyncEngine, source_version_id: UUID) -> IngestionRun:
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        run = await enqueue_ingestion(session, source_version_id, "test-pipeline")
        await session.commit()
        return run


async def claim(db_engine: AsyncEngine, worker_id: str):
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        result = await claim_next_job(session, worker_id, lease_seconds=30)
        await session.commit()
        return result


async def test_two_workers_cannot_claim_the_same_job(
    db_engine: AsyncEngine, source_version_id: UUID
) -> None:
    """Removing SKIP LOCKED or the lock lets concurrent workers duplicate processing."""
    run = await enqueue(db_engine, source_version_id)
    first, second = await asyncio.gather(claim(db_engine, "worker-a"), claim(db_engine, "worker-b"))

    claimed = [job for job in (first, second) if job is not None]
    assert [job.run_id for job in claimed] == [run.id]


async def test_expired_lease_is_retryable_with_the_next_attempt(
    db_engine: AsyncEngine, source_version_id: UUID
) -> None:
    """Ignoring an expired lease permanently abandons a job after its first worker dies."""
    await enqueue(db_engine, source_version_id)
    first = await claim(db_engine, "worker-a")
    assert first is not None
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        await session.execute(
            sa.update(IngestionJob)
            .where(IngestionJob.id == first.id)
            .values(lease_expires_at=sa.func.now() - timedelta(seconds=1))
        )
        await session.commit()

    retry = await claim(db_engine, "worker-b")

    assert retry is not None
    assert retry.id == first.id
    assert retry.attempt == 2


async def test_worker_must_own_a_live_lease_to_transition_job(
    db_engine: AsyncEngine, source_version_id: UUID
) -> None:
    """Removing ownership predicates permits a stale worker to overwrite a newer owner."""
    await enqueue(db_engine, source_version_id)
    claimed = await claim(db_engine, "worker-a")
    assert claimed is not None
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        with pytest.raises(JobLeaseLost):
            await complete_job(session, claimed.id, "worker-b")
        await session.rollback()

        heartbeat = await heartbeat_job(session, claimed.id, "worker-a", lease_seconds=30)
        assert heartbeat.worker_id == "worker-a"
        completed = await complete_job(session, claimed.id, "worker-a")
        await session.commit()

    assert completed.status == "succeeded"


async def test_failure_retries_then_records_a_bounded_terminal_error(
    db_engine: AsyncEngine, source_version_id: UUID
) -> None:
    """Skipping the retry cap causes permanently failing sources to run without bound."""
    run = await enqueue(db_engine, source_version_id)
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        job = await session.scalar(sa.select(IngestionJob).where(IngestionJob.run_id == run.id))
        assert job is not None
        job.max_attempts = 2
        await session.commit()

    first = await claim(db_engine, "worker-a")
    assert first is not None
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        retried = await fail_job(session, first.id, "worker-a", "parse_error", "x" * 5000)
        await session.commit()
    assert retried.status == "queued"

    second = await claim(db_engine, "worker-b")
    assert second is not None and second.attempt == 2
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        failed = await fail_job(session, second.id, "worker-b", "parse_error", "x" * 5000)
        await session.commit()

    assert failed.status == "failed"
    assert failed.error_code == "parse_error"
    assert len(failed.error_detail or "") == 1000


async def test_enqueue_is_idempotent_per_source_version_and_pipeline(
    db_engine: AsyncEngine, source_version_id: UUID
) -> None:
    """Removing the source-version/pipeline uniqueness boundary duplicates normalization."""
    first, second = await asyncio.gather(
        enqueue(db_engine, source_version_id), enqueue(db_engine, source_version_id)
    )

    assert first.id == second.id
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(IngestionRun)) == 1


async def test_cancel_requires_owner_and_is_terminal(
    db_engine: AsyncEngine, source_version_id: UUID
) -> None:
    """A non-owner must not be able to cancel a running job."""
    await enqueue(db_engine, source_version_id)
    claimed = await claim(db_engine, "worker-a")
    assert claimed is not None
    async with async_sessionmaker(db_engine, expire_on_commit=False)() as session:
        with pytest.raises(JobLeaseLost):
            await cancel_job(session, claimed.id, "worker-b")
        await session.rollback()
        cancelled = await cancel_job(session, claimed.id, "worker-a")
        await session.commit()

    assert cancelled.status == "cancelled"
