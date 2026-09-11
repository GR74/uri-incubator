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

from uri_backend.ingestion.adapters.documents import DocumentAdapter
from uri_backend.ingestion.contracts import AdapterInput
from uri_backend.ingestion.models import IngestionJob
from uri_backend.ingestion.queue import enqueue_ingestion
from uri_backend.ingestion.worker import build_default_dispatcher, run_worker
from uri_backend.projects.models import Project, ProjectMembership, User
from uri_backend.sources.models import Artifact, ContentPart, Source, SourceVersion

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
async def document_run(db_engine: AsyncEngine, tmp_path: Path):
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
