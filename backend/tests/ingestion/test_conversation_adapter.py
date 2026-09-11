from __future__ import annotations

import io
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from uri_backend.api import create_app
from uri_backend.config import Settings
from uri_backend.ingestion.adapters.conversations import (
    ConversationService,
    ExportMalformed,
    StageExpired,
    StagePurgeFailed,
)
from uri_backend.projects.models import AuditEvent, Project, ProjectMembership, User
from uri_backend.sources.artifacts import LocalArtifactStore
from uri_backend.sources.models import Source, SourceVersion


def synthetic_export() -> bytes:
    return json.dumps(
        [
            {
                "id": "conv-clearermind",
                "title": "Selected synthetic discussion",
                "create_time": 1700000000,
                "update_time": 1700000200,
                "current_node": "answer",
                "mapping": {
                    "root": {"id": "root", "parent": None, "message": None},
                    "prompt": {
                        "id": "prompt",
                        "parent": "root",
                        "message": {
                            "id": "msg-prompt",
                            "author": {"role": "user", "name": "Synthetic User"},
                            "create_time": 1700000001,
                            "content": {"parts": ["Selected research question"]},
                        },
                    },
                    "answer": {
                        "id": "answer",
                        "parent": "prompt",
                        "message": {
                            "id": "msg-answer",
                            "author": {"role": "assistant", "name": "Synthetic Assistant"},
                            "create_time": 1700000002,
                            "content": {"parts": ["Selected synthetic answer"]},
                        },
                    },
                    "branch": {
                        "id": "branch",
                        "parent": "prompt",
                        "message": {
                            "id": "msg-branch",
                            "author": {"role": "assistant"},
                            "content": {"parts": ["BRANCHED_UNSELECTED_MESSAGE"]},
                        },
                    },
                },
            },
            {
                "id": "conv-unrelated",
                "title": "Unselected synthetic discussion",
                "create_time": None,
                "update_time": None,
                "mapping": {
                    "only": {
                        "id": "only",
                        "parent": None,
                        "message": {
                            "id": "msg-unrelated",
                            "author": {"role": "user"},
                            "content": {"parts": ["UNSELECTED_SECRET_MARKER"]},
                        },
                    }
                },
            },
        ]
    ).encode("utf-8")


@pytest_asyncio.fixture(autouse=True)
async def clean_conversation_tables(db_engine: AsyncEngine) -> None:
    async with db_engine.begin() as connection:
        await connection.execute(
            sa.text(
                "TRUNCATE TABLE ingestion_job_attempts, ingestion_jobs, ingestion_runs, "
                "source_quality_assessments, content_parts, source_versions, sources, artifacts, "
                "audit_events, membership_capabilities, project_memberships, projects, labs, users CASCADE"
            )
        )


@pytest_asyncio.fixture
async def conversation_service(db_engine: AsyncEngine, tmp_path: Path):
    project_id, actor_id = uuid4(), uuid4()
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(id=actor_id, display_name="Conversation tester", is_pilot_actor=True),
                Project(id=project_id, name="Conversation project"),
            ]
        )
        await session.flush()
        session.add(ProjectMembership(user_id=actor_id, project_id=project_id, role="owner"))
        await session.commit()
    return ConversationService(
        factory,
        LocalArtifactStore(tmp_path / "artifacts", tmp_path / "artifact-staging"),
        tmp_path / "conversation-staging",
        actor_id,
        project_id,
    )


@pytest_asyncio.fixture
async def conversation_client(db_engine: AsyncEngine, tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        Settings(
            database_url="postgresql+psycopg://unused",
            artifact_root=tmp_path / "api-artifacts",
            staging_root=tmp_path / "api-staging",
        )
    )
    app.state.database_engine = db_engine
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def test_only_selected_conversations_are_promoted(conversation_service) -> None:
    """Persisting all export messages would breach explicit per-conversation consent."""
    inventory = conversation_service.inventory(io.BytesIO(synthetic_export()))

    promoted = await conversation_service.promote(inventory.stage_id, ["conv-clearermind"])

    assert [item.external_id for item in promoted] == ["conv-clearermind"]
    assert not inventory.staging_path.exists()
    async with conversation_service.session_factory() as session:
        unrelated = await session.scalar(
            sa.select(Source).where(Source.external_id == "conv-unrelated")
        )
        assert unrelated is None
        durable_text = " ".join(
            [
                *(await session.scalars(sa.select(Source.title))).all(),
                *(await session.scalars(sa.select(SourceVersion.metadata_))).all().__str__(),
                *(await session.scalars(sa.select(AuditEvent.metadata_))).all().__str__(),
            ]
        )
    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (conversation_service.artifact_store.root).rglob("*")
        if path.is_file()
    )
    assert "UNSELECTED_SECRET_MARKER" not in durable_text + artifact_text
    assert "BRANCHED_UNSELECTED_MESSAGE" not in artifact_text


async def test_expired_stage_cannot_be_promoted(conversation_service) -> None:
    """Ignoring TTL would retain raw conversation material after its allowed lifetime."""
    inventory = conversation_service.inventory(io.BytesIO(synthetic_export()), ttl=timedelta(seconds=-1))

    with pytest.raises(StageExpired):
        await conversation_service.promote(inventory.stage_id, ["conv-clearermind"])

    assert not inventory.staging_path.exists()


def test_malformed_export_is_purged_without_echoing_message_text(conversation_service) -> None:
    """A parser error must not leave or disclose a rejected export body."""
    with pytest.raises(ExportMalformed) as error:
        conversation_service.inventory(io.BytesIO(b'{"secret":"UNSELECTED_SECRET_MARKER"'))

    assert "UNSELECTED_SECRET_MARKER" not in str(error.value)
    assert list(conversation_service.staging_root.glob("*")) == []


def test_inventory_contains_metadata_but_never_message_bodies(conversation_service) -> None:
    """Previewing a stage must not expose content before the user selects it."""
    inventory = conversation_service.inventory(io.BytesIO(synthetic_export()))

    assert [(item.external_id, item.message_count) for item in inventory.conversations] == [
        ("conv-clearermind", 2),
        ("conv-unrelated", 1),
    ]
    assert "Selected research question" not in inventory.model_dump_json()
    conversation_service.cancel(inventory.stage_id)
    assert not inventory.staging_path.exists()


async def test_zero_selection_purges_the_export_without_creating_sources(
    conversation_service
) -> None:
    """Treating an empty selection as a default import would defeat consent."""
    inventory = conversation_service.inventory(io.BytesIO(synthetic_export()))

    promoted = await conversation_service.promote(inventory.stage_id, [])

    assert promoted == []
    assert not inventory.staging_path.exists()
    async with conversation_service.session_factory() as session:
        assert await session.scalar(sa.select(sa.func.count()).select_from(Source)) == 0


def test_oversized_export_is_rejected_and_purged(conversation_service) -> None:
    """Continuing past the byte cap permits a hostile export to exhaust staging storage."""
    oversized = io.BytesIO(b"[" + b" " * (16 * 1024 * 1024) + b"]")

    with pytest.raises(ExportMalformed, match="byte limit"):
        conversation_service.inventory(oversized)

    assert list(conversation_service.staging_root.glob("*")) == []


def test_purge_failure_is_visible_without_returning_export_content(
    conversation_service, monkeypatch
) -> None:
    """Swallowing cleanup errors leaves raw exports behind with no operator signal."""
    inventory = conversation_service.inventory(io.BytesIO(synthetic_export()))

    def fail_purge(_: Path) -> None:
        raise OSError("synthetic removal failure")

    monkeypatch.setattr("uri_backend.ingestion.adapters.conversations.shutil.rmtree", fail_purge)
    with pytest.raises(StagePurgeFailed) as error:
        conversation_service.cancel(inventory.stage_id)

    assert "UNSELECTED_SECRET_MARKER" not in str(error.value)


async def test_preview_then_selected_promotion_never_returns_unselected_bodies(
    conversation_client, conversation_service
) -> None:
    """Returning export content from an HTTP preview would bypass selection consent."""
    response = await conversation_client.post(
        f"/api/projects/{conversation_service.project_id}/sources/conversations/preview",
        headers={"X-URI-User-ID": str(conversation_service.actor_id)},
        content=synthetic_export(),
    )

    assert response.status_code == 201
    assert "UNSELECTED_SECRET_MARKER" not in response.text
    stage_id = response.json()["stage_id"]
    promoted = await conversation_client.post(
        f"/api/projects/{conversation_service.project_id}/sources/conversations/{stage_id}/promote",
        headers={"X-URI-User-ID": str(conversation_service.actor_id)},
        json={"conversation_ids": ["conv-clearermind"]},
    )
    assert promoted.status_code == 201
    assert [item["external_id"] for item in promoted.json()] == ["conv-clearermind"]
