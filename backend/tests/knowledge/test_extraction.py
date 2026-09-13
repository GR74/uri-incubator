from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.fakes import FakeStructuredProvider
from uri_backend.ingestion.models import IngestionJob
from uri_backend.ingestion.queue import claim_next_job, complete_job, enqueue_extraction
from uri_backend.ingestion.worker import build_extraction_handler
from uri_backend.knowledge.extraction import (
    CandidateBatch,
    ExtractionConfig,
    extract_candidates,
)
from uri_backend.knowledge.models import (
    CandidateCitation,
    DraftSet,
    Record,
)
from uri_backend.knowledge.schemas import CandidateCitationInput, ExtractedCandidate
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
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as claimed_session:
        claimed = await claim_next_job(claimed_session, "extract-test", lease_seconds=30)
        await claimed_session.commit()
    assert claimed is not None and claimed.run_id == run.id
    provider = FakeStructuredProvider(CandidateBatch(items=[ExtractedCandidate(
        candidate_key="worker", candidate_type="decision", statement="Use the revised method.",
        citations=[CandidateCitationInput(part_id=parts[0].id, quote="Use the revised method.")], confidence=0.9,
    )]))

    await build_extraction_handler(factory, provider, TEST_CONFIG)(claimed)

    async with factory() as verification:
        assert await verification.scalar(sa.select(sa.func.count()).select_from(DraftSet)) == 1
        await complete_job(verification, claimed.id, claimed.worker_id)
        await verification.commit()
