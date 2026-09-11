from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from uri_backend.ingestion.adapters import AdapterRegistry
from uri_backend.ingestion.adapters.documents import DocumentAdapter
from uri_backend.ingestion.contracts import (
    AdapterInput,
    NormalizationResult,
    NormalizationWarning,
    NormalizedPart,
)
from uri_backend.ingestion.models import IngestionJob, IngestionRun
from uri_backend.ingestion.queue import (
    ClaimedJob,
    claim_next_job,
    complete_job,
    enqueue_ingestion,
)
from uri_backend.ingestion.worker import (
    build_default_dispatcher,
    default_adapter_registry,
    persist_normalization,
    run_worker,
)
from uri_backend.projects.models import Project, ProjectMembership, User
from uri_backend.sources.models import (
    Artifact,
    ContentPart,
    Source,
    SourceQualityAssessment,
    SourceVersion,
)

DOCUMENT_FIXTURES = Path(__file__).parents[1] / "fixtures" / "document"
MEDIA_TYPES = {
    "sample.md": "text/markdown",
    "sample.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text.pdf": "application/pdf",
}


@pytest.mark.parametrize(
    ("fixture_name", "expected_kind", "locator_key"),
    [
        ("sample.md", "paragraph", "line_start"),
        ("sample.docx", "paragraph", "paragraph"),
        ("text.pdf", "page", "page"),
    ],
)
def test_documents_have_addressable_parts(
    fixture_name: str, expected_kind: str, locator_key: str
) -> None:
    """Dropping source locators makes normalized text impossible to audit."""
    result = DocumentAdapter().normalize(
        AdapterInput(
            artifact_path=DOCUMENT_FIXTURES / fixture_name,
            media_type=MEDIA_TYPES[fixture_name],
            family="document",
        )
    )

    assert result.status == "normalized"
    assert result.parts[0].kind == expected_kind
    assert locator_key in result.parts[0].locator


def test_scanned_pdf_requests_ocr_without_inventing_text() -> None:
    """Treating an image-only PDF as text would manufacture research evidence."""
    result = DocumentAdapter().normalize(
        AdapterInput(
            artifact_path=DOCUMENT_FIXTURES / "scanned.pdf",
            media_type="application/pdf",
            family="document",
        )
    )

    assert result.status == "needs_ocr"
    assert result.parts == []
    assert result.warnings[0].code == "no_extractable_text"


def test_markdown_keeps_one_based_paragraph_line_spans() -> None:
    """Collapsing blank-line boundaries loses a stable citation location."""
    result = DocumentAdapter().normalize(
        AdapterInput(
            artifact_path=DOCUMENT_FIXTURES / "sample.md",
            media_type="text/markdown",
            family="document",
        )
    )

    assert [part.locator for part in result.parts] == [
        {"line_start": 1, "line_end": 1},
        {"line_start": 3, "line_end": 4},
    ]


def test_malformed_document_reports_visible_parse_failure(tmp_path: Path) -> None:
    """Silently accepting invalid bytes hides a corrupted artifact."""
    malformed = tmp_path / "broken.md"
    malformed.write_bytes(b"\xff")

    result = DocumentAdapter().normalize(
        AdapterInput(artifact_path=malformed, media_type="text/markdown", family="document")
    )

    assert result.status == "failed"
    assert result.parts == []
    assert result.warnings[0].code == "encoding_error"


@pytest_asyncio.fixture
async def clean_document_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "TRUNCATE TABLE ingestion_job_attempts, ingestion_jobs, ingestion_runs, "
                "source_quality_assessments, content_parts, source_versions, sources, artifacts, "
                "audit_events, membership_capabilities, project_memberships, projects, labs, users CASCADE"
            )
        )


@pytest_asyncio.fixture
async def document_run(clean_document_tables, db_engine: AsyncEngine, tmp_path: Path):
    artifact_root = tmp_path / "artifacts"
    content = (DOCUMENT_FIXTURES / "sample.md").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    storage_key = f"{digest[:2]}/{digest[2:]}"
    artifact_path = artifact_root / storage_key
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(content)
    project_id, user_id, source_id, artifact_id, version_id = (uuid4() for _ in range(5))
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(id=user_id, display_name="Document tester", is_pilot_actor=True),
                Project(id=project_id, name="Document project"),
                Artifact(id=artifact_id, sha256=digest, storage_key=storage_key, byte_size=len(content)),
            ]
        )
        await session.flush()
        session.add_all(
            [
                ProjectMembership(user_id=user_id, project_id=project_id, role="owner"),
                Source(id=source_id, project_id=project_id, family="document", external_id="sample.md"),
                SourceVersion(
                    id=version_id,
                    source_id=source_id,
                    project_id=project_id,
                    artifact_id=artifact_id,
                    family="document",
                    external_id="sample.md",
                    native_version="v1",
                    media_type="text/markdown",
                    created_by=user_id,
                ),
            ]
        )
        run = await enqueue_ingestion(session, version_id, "normalization-v1")
        await session.commit()
    return factory, artifact_root, run


@pytest.mark.skipif(
    not os.environ.get("URI_TEST_DATABASE_URL"),
    reason="requires explicitly configured isolated PostgreSQL",
)
async def test_normalization_worker_persists_ordered_parts_atomically(
    clean_document_tables, document_run
) -> None:
    """Skipping the worker write leaves a completed source with no auditable content parts."""
    factory, artifact_root, run = document_run
    dispatcher = build_default_dispatcher(factory, artifact_root)
    worker = asyncio.create_task(
        run_worker(factory, dispatcher=dispatcher, worker_id="document-worker", poll_seconds=10)
    )
    try:
        for _ in range(40):
            async with factory() as session:
                status = await session.scalar(
                    sa.select(IngestionJob.status).where(IngestionJob.run_id == run.id)
                )
                if status == "succeeded":
                    parts = (
                        await session.scalars(
                            sa.select(ContentPart)
                            .where(ContentPart.source_version_id == run.source_version_id)
                            .order_by(ContentPart.ordinal)
                        )
                    ).all()
                    break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("normalization worker did not complete")
    finally:
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker

    assert [(part.ordinal, part.locator) for part in parts] == [
        (1, {"line_start": 1, "line_end": 1}),
        (2, {"line_start": 3, "line_end": 4}),
    ]


def test_default_dispatcher_registers_normalization_handler() -> None:
    """Leaving the CLI composition empty causes valid normalization jobs to fail before polling."""
    dispatcher = build_default_dispatcher()

    assert dispatcher.can_dispatch("normalization-v1") is True


def _claimed_normalization_job(run) -> ClaimedJob:
    return ClaimedJob(id=uuid4(), run_id=run.id, attempt=1, pipeline_version="normalization-v1")


async def _add_part(factory, run, *, text: str, ordinal: int = 1) -> None:
    async with factory() as session:
        session.add(
            ContentPart(
                source_version_id=run.source_version_id,
                ordinal=ordinal,
                kind="paragraph",
                text=text,
                locator={"line_start": ordinal, "line_end": ordinal},
                metadata_={"ingestion_run_id": str(run.id)},
            )
        )
        await session.commit()


@pytest.mark.skipif(
    not os.environ.get("URI_TEST_DATABASE_URL"),
    reason="requires explicitly configured isolated PostgreSQL",
)
async def test_retry_replaces_only_unpublished_parts_for_its_same_run(document_run) -> None:
    """A retry must replace its own stale partial output rather than duplicate it."""
    factory, artifact_root, run = document_run
    async with factory() as session:
        persisted_run = await session.get(IngestionRun, run.id)
        assert persisted_run is not None
        persisted_run.status = "running"
        await session.commit()
    await _add_part(factory, run, text="stale partial output")

    await persist_normalization(
        factory, _claimed_normalization_job(run), artifact_root, default_adapter_registry()
    )

    async with factory() as session:
        parts = (
            await session.scalars(
                sa.select(ContentPart)
                .where(ContentPart.source_version_id == run.source_version_id)
                .order_by(ContentPart.ordinal)
            )
        ).all()
    assert [part.text for part in parts] == [
        "URI document heading",
        "First fictional research note.\nSecond fictional research note.",
    ]


@pytest.mark.skipif(
    not os.environ.get("URI_TEST_DATABASE_URL"),
    reason="requires explicitly configured isolated PostgreSQL",
)
async def test_crash_after_normalization_reuses_one_immutable_quality_assessment(
    document_run,
) -> None:
    """A recovered lease must not append a second immutable quality report."""
    factory, artifact_root, run = document_run
    async with factory() as session:
        first = await claim_next_job(session, "worker-before-crash", lease_seconds=30)
        await session.commit()
    assert first is not None
    await persist_normalization(
        factory, first, artifact_root, default_adapter_registry()
    )
    async with factory() as session:
        await session.execute(
            sa.update(IngestionJob)
            .where(IngestionJob.id == first.id)
            .values(lease_expires_at=sa.func.now() - sa.text("interval '1 second'"))
        )
        await session.commit()
    async with factory() as session:
        retry = await claim_next_job(session, "worker-after-crash", lease_seconds=30)
        await session.commit()
    assert retry is not None and retry.attempt == 2
    await persist_normalization(
        factory, retry, artifact_root, default_adapter_registry()
    )
    async with factory() as session:
        await complete_job(session, retry.id, "worker-after-crash")
        await session.commit()
        assessments = await session.scalars(
            sa.select(SourceQualityAssessment).where(
                SourceQualityAssessment.source_version_id == run.source_version_id
            )
        )
        parts = await session.scalars(
            sa.select(ContentPart).where(
                ContentPart.source_version_id == run.source_version_id
            )
        )

    assert len(list(assessments)) == 1
    assert len(list(parts)) == 2


@pytest.mark.skipif(
    not os.environ.get("URI_TEST_DATABASE_URL"),
    reason="requires explicitly configured isolated PostgreSQL",
)
async def test_successful_run_parts_reject_deletion_even_with_matching_session_token(document_run) -> None:
    """A mutable session token alone must never permit deletion of published parts."""
    factory, _, run = document_run
    await _add_part(factory, run, text="published output")
    async with factory() as session:
        persisted_run = await session.get(IngestionRun, run.id)
        assert persisted_run is not None
        persisted_run.status = "succeeded"
        await session.commit()

    async with factory() as session:
        await session.execute(
            sa.text("SELECT set_config('uri.ingestion_run_id', :run_id, true)"),
            {"run_id": str(run.id)},
        )
        with pytest.raises(sa.exc.DBAPIError):
            await session.execute(
                sa.delete(ContentPart).where(ContentPart.source_version_id == run.source_version_id)
            )
        await session.rollback()

    async with factory() as session:
        assert await session.scalar(
            sa.select(sa.func.count()).select_from(ContentPart)
        ) == 1


@pytest.mark.skipif(
    not os.environ.get("URI_TEST_DATABASE_URL"),
    reason="requires explicitly configured isolated PostgreSQL",
)
async def test_different_run_parts_reject_deletion_from_current_run(document_run) -> None:
    """A current retry must not use its token to mutate an earlier run's output."""
    factory, _, run = document_run
    earlier_run = IngestionRun(
        source_version_id=run.source_version_id,
        pipeline_version="normalization-earlier-v1",
        idempotency_key="normalization-earlier-v1",
        status="running",
    )
    async with factory() as session:
        session.add(earlier_run)
        await session.commit()
    await _add_part(factory, earlier_run, text="earlier output")

    async with factory() as session:
        await session.execute(
            sa.text("SELECT set_config('uri.ingestion_run_id', :run_id, true)"),
            {"run_id": str(run.id)},
        )
        with pytest.raises(sa.exc.DBAPIError):
            await session.execute(
                sa.delete(ContentPart).where(ContentPart.source_version_id == run.source_version_id)
            )
        await session.rollback()


@pytest.mark.skipif(
    not os.environ.get("URI_TEST_DATABASE_URL"),
    reason="requires explicitly configured isolated PostgreSQL",
)
async def test_failed_normalization_rolls_back_replacement_deletion(document_run) -> None:
    """A parser failure must retain old parts because replacement is one transaction."""
    factory, artifact_root, run = document_run
    async with factory() as session:
        persisted_run = await session.get(IngestionRun, run.id)
        assert persisted_run is not None
        persisted_run.status = "running"
        await session.commit()
    await _add_part(factory, run, text="stale output")

    class FailingAdapter:
        def supports(self, context: AdapterInput) -> bool:
            return True

        def normalize(self, context: AdapterInput) -> NormalizationResult:
            return NormalizationResult(
                adapter="failing",
                adapter_version="v1",
                status="failed",
                parts=[],
                warnings=[NormalizationWarning(code="parse_error", message="synthetic failure")],
                parse_coverage=0.0,
            )

    with pytest.raises(ValueError, match="Document normalization failed"):
        await persist_normalization(
            factory,
            _claimed_normalization_job(run),
            artifact_root,
            AdapterRegistry([FailingAdapter()]),
        )

    async with factory() as session:
        parts = (await session.scalars(sa.select(ContentPart))).all()
    assert [part.text for part in parts] == ["stale output"]


@pytest.mark.skipif(
    not os.environ.get("URI_TEST_DATABASE_URL"),
    reason="requires explicitly configured isolated PostgreSQL",
)
async def test_partial_insert_failure_rolls_back_replacement_deletion(document_run) -> None:
    """A database failure after replacement starts must restore the old complete part set."""
    factory, artifact_root, run = document_run
    async with factory() as session:
        persisted_run = await session.get(IngestionRun, run.id)
        assert persisted_run is not None
        persisted_run.status = "running"
        await session.commit()
    await _add_part(factory, run, text="stale output")

    class DuplicateOrdinalAdapter:
        def supports(self, context: AdapterInput) -> bool:
            return True

        def normalize(self, context: AdapterInput) -> NormalizationResult:
            return NormalizationResult(
                adapter="duplicate",
                adapter_version="v1",
                status="normalized",
                parts=[
                    NormalizedPart(
                        ordinal=1,
                        kind="paragraph",
                        text="first new part",
                        locator={"line_start": 1, "line_end": 1},
                    ),
                    NormalizedPart(
                        ordinal=1,
                        kind="paragraph",
                        text="duplicate new part",
                        locator={"line_start": 2, "line_end": 2},
                    ),
                ],
                parse_coverage=1.0,
            )

    with pytest.raises(sa.exc.IntegrityError):
        await persist_normalization(
            factory,
            _claimed_normalization_job(run),
            artifact_root,
            AdapterRegistry([DuplicateOrdinalAdapter()]),
        )

    async with factory() as session:
        parts = (await session.scalars(sa.select(ContentPart))).all()
    assert [part.text for part in parts] == ["stale output"]
