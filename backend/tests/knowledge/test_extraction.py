from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.fakes import FakeStructuredProvider
from uri_backend.ingestion.models import (
    ExtractionRun,
    IngestionJob,
    IngestionJobAttempt,
)
from uri_backend.ingestion.queue import (
    ClaimedJob,
    JobLeaseLost,
    claim_next_job,
    enqueue_extraction,
    fail_job,
)
from uri_backend.ingestion.worker import build_extraction_handler
from uri_backend.knowledge.extraction import (
    CandidateBatch,
    ExtractionConfig,
    _contradicts,
    _windows,
    extract_candidates,
)
from uri_backend.knowledge.models import (
    CandidateCitation,
    DraftRelation,
    DraftSet,
    Record,
)
from uri_backend.knowledge.schemas import (
    CandidateCitationInput,
    ExtractedCandidate,
    ExtractedRelation,
    RelationEndpointReference,
)
from uri_backend.projects.models import Project, User
from uri_backend.sources.models import Artifact, ContentPart, Source, SourceVersion

FIXTURE = Path(__file__).parents[1] / "fixtures" / "extraction" / "clearermind_synthetic_parts.json"
TEST_CONFIG = ExtractionConfig(
    model_id="synthetic-clearermind-model",
    model_digest="sha256:synthetic",
    prompt_version="extraction-prompt-v1",
    schema_version="candidate-batch-v1",
    parser_version="normalization-v1",
    sampling_config={"temperature": 0},
    sampling_version="sampling-v1",
)


@pytest.fixture(autouse=True)
async def clean_extraction_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "TRUNCATE TABLE extraction_runs, supersessions, relation_citations, relations, "
                "record_citations, record_versions, records, reviews, draft_relation_citations, "
                "draft_relations, candidate_citations, draft_candidates, draft_sets, "
                "source_quality_assessments, content_parts, source_versions, sources, artifacts, "
                "audit_events, membership_capabilities, project_memberships, projects, labs, users CASCADE"
            )
        )


@pytest.fixture
async def seed_parts(db_engine: AsyncEngine) -> tuple[AsyncSession, SourceVersion, list[ContentPart]]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    session = factory()
    project_id, author_id = uuid4(), uuid4()
    session.add_all([
        User(id=author_id, display_name="Synthetic researcher", is_pilot_actor=True),
        Project(id=project_id, name="Synthetic ClearerMind"),
        Artifact(sha256="b" * 64, storage_key="bb/" + "b" * 62, byte_size=1),
    ])
    await session.flush()
    artifact = await session.scalar(sa.select(Artifact))
    assert artifact is not None
    source = Source(project_id=project_id, family="document", external_id="clearermind-synthetic")
    session.add(source)
    await session.flush()
    version = SourceVersion(
        source_id=source.id, project_id=project_id, artifact_id=artifact.id,
        family="document", external_id="clearermind-synthetic", native_version="v1",
        media_type="text/plain", created_by=author_id,
    )
    session.add(version)
    await session.flush()
    parts = [ContentPart(source_version_id=version.id, **item) for item in json.loads(FIXTURE.read_text())]
    session.add_all(parts)
    await session.commit()
    try:
        yield session, version, parts
    finally:
        await session.close()


async def test_extraction_discards_unknown_citation_locator(
    seed_parts: tuple[AsyncSession, SourceVersion, list[ContentPart]],
) -> None:
    """Accepting an unowned part ID would create a draft with fabricated evidence."""
    session, version, _ = seed_parts
    provider = FakeStructuredProvider(CandidateBatch(items=[ExtractedCandidate(
        candidate_key="unknown", candidate_type="decision", statement="Use the revised method.",
        citations=[CandidateCitationInput(part_id=uuid4(), quote="Use the revised method")], confidence=0.9,
    )]))

    draft = await extract_candidates(session, version.id, provider, TEST_CONFIG)

    assert draft.candidates == []
    assert draft.validation_warnings[0].code == "unknown_citation_part"


async def test_extraction_persists_exact_quote_without_publishing(
    seed_parts: tuple[AsyncSession, SourceVersion, list[ContentPart]],
) -> None:
    """Dropping citation fidelity or publishing directly would make model output unreviewable."""
    session, version, parts = seed_parts
    provider = FakeStructuredProvider(CandidateBatch(items=[ExtractedCandidate(
        candidate_key="revised-method", candidate_type="decision", statement="Use the revised method.",
        citations=[CandidateCitationInput(part_id=parts[0].id, quote="Use   the revised method.")], confidence=0.9,
    )]))

    draft = await extract_candidates(session, version.id, provider, TEST_CONFIG)

    assert len(draft.candidates) == 1
    assert await session.scalar(sa.select(sa.func.count()).select_from(CandidateCitation)) == 1
    assert await session.scalar(sa.select(sa.func.count()).select_from(Record)) == 0
    assert draft.candidates[0].statement == "Use the revised method."


async def test_extraction_deduplicates_only_identical_cited_statements(
    seed_parts: tuple[AsyncSession, SourceVersion, list[ContentPart]],
) -> None:
    """Collapsing merely similar claims would hide a conflict requiring review."""
    session, version, parts = seed_parts
    citation = CandidateCitationInput(part_id=parts[0].id, quote="Use the revised method.")
    provider = FakeStructuredProvider(CandidateBatch(items=[
        ExtractedCandidate(candidate_key="one", candidate_type="decision", statement="Use the revised method.", citations=[citation], confidence=0.9),
        ExtractedCandidate(candidate_key="duplicate", candidate_type="decision", statement="Use the revised method.", citations=[citation], confidence=0.9),
        ExtractedCandidate(candidate_key="conflict", candidate_type="decision", statement="Do not use the revised method.", citations=[citation], confidence=0.8),
    ]))

    draft = await extract_candidates(session, version.id, provider, TEST_CONFIG)

    assert len(draft.candidates) == 2
    assert any(warning.code == "duplicate_candidate" for warning in draft.validation_warnings)
    assert any(warning.code == "possible_conflict" for warning in draft.validation_warnings)


async def test_extraction_rejects_unsupported_dates_and_keeps_valid_items(
    seed_parts: tuple[AsyncSession, SourceVersion, list[ContentPart]],
) -> None:
    """Permitting an uncited event date would turn a model inference into source evidence."""
    session, version, parts = seed_parts
    provider = FakeStructuredProvider(CandidateBatch(items=[
        ExtractedCandidate(candidate_key="dated", candidate_type="result", statement="A dated result.", event_time="2026-09-13T00:00:00Z", citations=[CandidateCitationInput(part_id=parts[0].id, quote="reported a difference")], confidence=0.7),
        ExtractedCandidate(candidate_key="valid", candidate_type="decision", statement="Use the revised method.", citations=[CandidateCitationInput(part_id=parts[0].id, quote="Use the revised method.")], confidence=0.9),
    ]))

    draft = await extract_candidates(session, version.id, provider, TEST_CONFIG)

    assert [candidate.statement for candidate in draft.candidates] == ["Use the revised method."]
    assert any(warning.code == "unsupported_event_time" for warning in draft.validation_warnings)


async def test_extraction_enqueue_is_idempotent_for_one_normalized_version(
    seed_parts: tuple[AsyncSession, SourceVersion, list[ContentPart]],
) -> None:
    """Creating a second extraction job on retry would duplicate review work."""
    session, version, _ = seed_parts

    first = await enqueue_extraction(session, version.id)
    second = await enqueue_extraction(session, version.id)
    await session.commit()

    assert first.id == second.id
    assert await session.scalar(sa.select(sa.func.count()).select_from(IngestionJob)) == 1


async def test_worker_handler_commits_draft_before_job_completion(
    db_engine: AsyncEngine,
    seed_parts: tuple[AsyncSession, SourceVersion, list[ContentPart]],
) -> None:
    """Completing a lease first would permanently lose a crash-interrupted extraction draft."""
    session, version, parts = seed_parts
    run = await enqueue_extraction(session, version.id)
    await session.commit()
    await session.close()
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as claimed_session:
        job = await claimed_session.scalar(sa.select(IngestionJob).where(IngestionJob.run_id == run.id))
        assert job is not None
        job.status, job.worker_id, job.attempt = "running", "extract-test", 1
        job.lease_expires_at = sa.func.now() + sa.text("interval '30 seconds'")
        await claimed_session.commit()
    claimed = ClaimedJob(job.id, run.id, 1, "extraction-v1", "extract-test")
    provider = FakeStructuredProvider(CandidateBatch(items=[ExtractedCandidate(
        candidate_key="worker", candidate_type="decision", statement="Use the revised method.",
        citations=[CandidateCitationInput(part_id=parts[0].id, quote="Use the revised method.")], confidence=0.9,
    )]))

    await build_extraction_handler(factory, provider, TEST_CONFIG)(claimed)

    async with factory() as verification:
        assert await verification.scalar(sa.select(sa.func.count()).select_from(DraftSet)) == 1


def test_windows_split_one_oversized_part_with_stable_offsets() -> None:
    """A context-sized part must not silently make an extraction request unbounded."""
    part = ContentPart(id=uuid4(), ordinal=1, kind="paragraph", text="abcdefghij", locator={"line": 1}, source_version_id=uuid4())

    windows = _windows([part], 4)

    assert [window["parts"][0]["text"] for window in windows] == ["abcd", "efgh", "ij"]
    assert [window["parts"][0]["offset_start"] for window in windows] == [0, 4, 8]


async def test_extraction_calls_provider_once_per_bounded_window(seed_parts) -> None:
    session, version, _ = seed_parts
    provider = FakeStructuredProvider(CandidateBatch())
    await extract_candidates(session, version.id, provider, replace(TEST_CONFIG, max_window_characters=20))
    assert len(provider.requests) > 1
    assert all(len(request.messages[1]["content"]["parts"][0]["text"]) <= 20 for request in provider.requests)


async def test_duplicate_key_alias_preserves_relation(seed_parts) -> None:
    session, version, parts = seed_parts
    citation = CandidateCitationInput(part_id=parts[0].id, quote="Use the revised method.")
    provider = FakeStructuredProvider(CandidateBatch(
        items=[
            ExtractedCandidate(candidate_key="one", candidate_type="decision", statement="Use the revised method.", citations=[citation], confidence=0.9),
            ExtractedCandidate(candidate_key="two", candidate_type="decision", statement="Use the revised method.", citations=[citation], confidence=0.9),
            ExtractedCandidate(candidate_key="target", candidate_type="result", statement="The synthetic ClearerMind analysis reported a difference.", citations=[CandidateCitationInput(part_id=parts[0].id, quote="reported a difference")], confidence=0.8),
        ],
        relations=[ExtractedRelation(source=RelationEndpointReference(candidate_key="two"), target=RelationEndpointReference(candidate_key="target"), relation_type="supports", citations=[citation])],
    ))
    await extract_candidates(session, version.id, provider, TEST_CONFIG)
    assert await session.scalar(sa.select(sa.func.count()).select_from(DraftRelation)) == 1


def test_schema_and_conflict_boundaries_reject_blanks_without_substring_guessing() -> None:
    with pytest.raises(ValueError):
        CandidateCitationInput(part_id=uuid4(), quote="  ")
    with pytest.raises(ValueError):
        ExtractedCandidate(candidate_key="x", candidate_type="decision", statement=" ", citations=[CandidateCitationInput(part_id=uuid4(), quote="evidence")], confidence=0.5)
    with pytest.raises(ValueError):
        ExtractedCandidate(candidate_key="x", candidate_type="decision", statement="evidence", actors=[" "], citations=[CandidateCitationInput(part_id=uuid4(), quote="evidence")], confidence=0.5)
    assert _contradicts("Use revised method", "Do not use revised method")
    assert not _contradicts("Use revised method", "Use alternative method")


async def test_warning_does_not_store_model_key(seed_parts) -> None:
    session, version, _ = seed_parts
    private = "PRIVATE synthetic ClearerMind phrase"
    provider = FakeStructuredProvider(CandidateBatch(items=[ExtractedCandidate(candidate_key=private, candidate_type="decision", statement="Use the revised method.", citations=[CandidateCitationInput(part_id=uuid4(), quote="Use")], confidence=0.9)]))
    draft = await extract_candidates(session, version.id, provider, TEST_CONFIG)
    assert private not in json.dumps([warning.__dict__ for warning in draft.validation_warnings])


async def test_stale_extraction_attempt_cannot_publish_draft(db_engine, seed_parts) -> None:
    """A worker that lost its lease must fail before the review-only transaction."""
    session, version, parts = seed_parts
    await enqueue_extraction(session, version.id)
    await session.commit()
    await session.close()
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as claim_session:
        await claim_session.execute(sa.update(IngestionJob).values(available_at=sa.func.now() - sa.text("interval '1 second'")))
        await claim_session.commit()
        claimed = await claim_next_job(claim_session, "stale-extractor", 30)
        await claim_session.commit()
    assert claimed is not None
    async with factory() as expire_session:
        await expire_session.execute(sa.update(IngestionJob).where(IngestionJob.id == claimed.id).values(lease_expires_at=sa.func.now() - sa.text("interval '1 second'")))
        await expire_session.commit()
    provider = FakeStructuredProvider(CandidateBatch(items=[ExtractedCandidate(candidate_key="stale", candidate_type="decision", statement="Use the revised method.", citations=[CandidateCitationInput(part_id=parts[0].id, quote="Use the revised method.")], confidence=0.9)]))

    with pytest.raises(JobLeaseLost):
        await build_extraction_handler(factory, provider, TEST_CONFIG)(claimed)

    async with factory() as verification:
        assert await verification.scalar(sa.select(sa.func.count()).select_from(DraftSet)) == 0


async def test_attempt_provenance_stays_distinct_and_terminal_failure_stops(db_engine, seed_parts) -> None:
    session, version, _ = seed_parts
    run = await enqueue_extraction(session, version.id)
    await session.commit()
    await session.close()
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        job = await setup.scalar(sa.select(IngestionJob).where(IngestionJob.run_id == run.id))
        assert job is not None
        job.status, job.worker_id, job.attempt = "running", "test", 1
        job.lease_expires_at = sa.func.now() + sa.text("interval '30 seconds'")
        setup.add(IngestionJobAttempt(job_id=job.id, attempt=1, worker_id="test"))
        setup.add_all([
            ExtractionRun(source_version_id=version.id, ingestion_run_id=run.id, job_id=job.id, attempt=1, worker_id="test", pipeline_version="extraction-v1", model_id="a", model_digest="sha256:a", prompt_version="p1", schema_version="s1", parser_version="n1", sampling_config={"temperature": 0}, sampling_version="v1", status="failed"),
            ExtractionRun(source_version_id=version.id, ingestion_run_id=run.id, job_id=job.id, attempt=2, worker_id="test", pipeline_version="extraction-v1", model_id="b", model_digest="sha256:b", prompt_version="p2", schema_version="s1", parser_version="n1", sampling_config={"temperature": 0}, sampling_version="v1", status="retry"),
        ])
        await setup.flush()
        await fail_job(setup, job.id, "test", "provider_schema_invalid", "Provider extraction failed", terminal=True)
        await setup.commit()
    async with factory() as verify:
        rows = (await verify.scalars(sa.select(ExtractionRun).order_by(ExtractionRun.attempt))).all()
        job = await verify.scalar(sa.select(IngestionJob).where(IngestionJob.run_id == run.id))
        assert [(row.attempt, row.model_digest) for row in rows] == [(1, "sha256:a"), (2, "sha256:b")]
        assert job is not None and job.status == "failed"


async def test_retryable_provider_failure_returns_job_to_queue(db_engine, seed_parts) -> None:
    session, version, _ = seed_parts
    run = await enqueue_extraction(session, version.id)
    await session.commit()
    await session.close()
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        job = await setup.scalar(sa.select(IngestionJob).where(IngestionJob.run_id == run.id))
        assert job is not None
        job.status, job.worker_id, job.attempt = "running", "retry", 1
        job.lease_expires_at = sa.func.now() + sa.text("interval '30 seconds'")
        setup.add(IngestionJobAttempt(job_id=job.id, attempt=1, worker_id="retry"))
        await setup.flush()
        await fail_job(setup, job.id, "retry", "provider_timeout", "Provider extraction failed")
        await setup.commit()
    async with factory() as verify:
        job = await verify.scalar(sa.select(IngestionJob).where(IngestionJob.run_id == run.id))
        assert job is not None and job.status == "queued" and job.attempt == 1
