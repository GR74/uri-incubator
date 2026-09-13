from __future__ import annotations

import asyncio
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
    promote_selected_conversations,
    purge_expired_conversation_stages,
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
                            "author": {
                                "role": "assistant",
                                "name": "Synthetic Assistant",
                            },
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
                User(
                    id=actor_id, display_name="Conversation tester", is_pilot_actor=True
                ),
                Project(id=project_id, name="Conversation project"),
            ]
        )
        await session.flush()
        session.add(
            ProjectMembership(user_id=actor_id, project_id=project_id, role="owner")
        )
        await session.commit()
    return ConversationService(
        factory,
        LocalArtifactStore(tmp_path / "artifacts", tmp_path / "artifact-staging"),
        tmp_path / "conversation-staging",
        actor_id,
        project_id,
    )


@pytest_asyncio.fixture
async def conversation_client(
    db_engine: AsyncEngine, tmp_path: Path
) -> httpx.AsyncClient:
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

    promoted = await conversation_service.promote(
        inventory.stage_id, ["conv-clearermind"]
    )

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
                *(await session.scalars(sa.select(SourceVersion.metadata_)))
                .all()
                .__str__(),
                *(await session.scalars(sa.select(AuditEvent.metadata_)))
                .all()
                .__str__(),
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
    inventory = conversation_service.inventory(
        io.BytesIO(synthetic_export()), ttl=timedelta(seconds=-1)
    )

    with pytest.raises(StageExpired):
        await conversation_service.promote(inventory.stage_id, ["conv-clearermind"])

    assert not inventory.staging_path.exists()


def test_malformed_export_is_purged_without_echoing_message_text(
    conversation_service,
) -> None:
    """A parser error must not leave or disclose a rejected export body."""
    with pytest.raises(ExportMalformed) as error:
        conversation_service.inventory(
            io.BytesIO(b'{"secret":"UNSELECTED_SECRET_MARKER"')
        )

    assert "UNSELECTED_SECRET_MARKER" not in str(error.value)
    assert not any(
        path.is_file() for path in conversation_service.staging_root.rglob("*")
    )


def test_inventory_contains_metadata_but_never_message_bodies(
    conversation_service,
) -> None:
    """Previewing a stage must not expose content before the user selects it."""
    inventory = conversation_service.inventory(io.BytesIO(synthetic_export()))

    assert [
        (item.external_id, item.message_count) for item in inventory.conversations
    ] == [
        ("conv-clearermind", 2),
        ("conv-unrelated", 1),
    ]
    assert "Selected research question" not in inventory.model_dump_json()
    conversation_service.cancel(inventory.stage_id)
    assert not inventory.staging_path.exists()


async def test_zero_selection_purges_the_export_without_creating_sources(
    conversation_service,
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

    assert not any(
        path.is_file() for path in conversation_service.staging_root.rglob("*")
    )


def test_purge_failure_is_visible_without_returning_export_content(
    conversation_service, monkeypatch
) -> None:
    """Swallowing cleanup errors leaves raw exports behind with no operator signal."""
    inventory = conversation_service.inventory(io.BytesIO(synthetic_export()))

    def fail_purge(_: Path) -> None:
        raise OSError("synthetic removal failure")

    monkeypatch.setattr(
        "uri_backend.ingestion.adapters.conversations.shutil.rmtree", fail_purge
    )
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


def test_janitor_purges_expired_stage_without_a_follow_up_request(
    conversation_service,
) -> None:
    """An abandoned export must not wait for another client request before deletion."""
    inventory = conversation_service.inventory(
        io.BytesIO(synthetic_export()), ttl=timedelta(seconds=-1)
    )

    result = purge_expired_conversation_stages(conversation_service.staging_root)

    assert result.purged_stage_ids == [inventory.stage_id]
    assert result.failures == []
    assert not inventory.staging_path.exists()


async def test_restart_discovers_stage_and_public_promotion_interface(
    conversation_service,
) -> None:
    """Losing process memory must not strand a selected stage or its TTL metadata."""
    inventory = conversation_service.inventory(io.BytesIO(synthetic_export()))
    restarted = ConversationService(
        conversation_service.session_factory,
        conversation_service.artifact_store,
        conversation_service.staging_root,
        conversation_service.actor_id,
        conversation_service.project_id,
    )
    async with restarted.session_factory() as session:
        actor = await session.get(User, restarted.actor_id)
        project = await session.get(Project, restarted.project_id)
        assert actor is not None
        assert project is not None
        promoted = await promote_selected_conversations(
            inventory.stage_id,
            ["conv-clearermind"],
            actor,
            project,
            service=restarted,
        )

    assert [version.external_id for version in promoted] == ["conv-clearermind"]
    assert not inventory.staging_path.exists()


async def test_app_janitor_stops_cleanly_after_lifespan(tmp_path: Path) -> None:
    """A shutdown that leaves the cleanup task alive can retain exports after app exit."""
    app = create_app(
        Settings(
            database_url=None,
            artifact_root=tmp_path / "artifacts",
            staging_root=tmp_path / "staging",
            conversation_stage_cleanup_seconds=1,
        )
    )
    service = ConversationService(
        async_sessionmaker(),
        LocalArtifactStore(tmp_path / "artifacts"),
        tmp_path / "staging" / "conversation-exports",
        uuid4(),
        uuid4(),
    )
    inventory = service.inventory(
        io.BytesIO(synthetic_export()), ttl=timedelta(seconds=-1)
    )
    async with app.router.lifespan_context(app):
        task = app.state.conversation_stage_janitor_task
        for _ in range(20):
            if not inventory.staging_path.exists():
                break
            await asyncio.sleep(0.01)
        assert not task.done()
        assert not inventory.staging_path.exists()

    assert task.done()
    assert task.cancelled()


def test_janitor_reports_root_traversal_failure_and_retries(
    conversation_service, monkeypatch
) -> None:
    """A transient staging-root read error must not permanently disable expiry cleanup."""
    conversation_service.staging_root.mkdir()
    original_iterdir = Path.iterdir
    calls = 0

    def fail_once(path: Path):
        nonlocal calls
        if path == conversation_service.staging_root and calls == 0:
            calls += 1
            raise OSError("synthetic traversal failure")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_once)

    failed = purge_expired_conversation_stages(conversation_service.staging_root)
    recovered = purge_expired_conversation_stages(conversation_service.staging_root)

    assert failed.failures == ["staging_root"]
    assert recovered.failures == []


async def test_janitor_between_upload_chunks_preserves_live_intake(
    conversation_service,
):
    """A stage directory visible before stage.json must not be purged during upload."""
    body = synthetic_export()

    async def chunks():
        yield body[:30]
        result = purge_expired_conversation_stages(conversation_service.staging_root)
        assert result.purged_stage_ids == []
        assert result.failures == []
        yield body[30:]

    inventory = await conversation_service.inventory_async(chunks())
    assert len(inventory.conversations) == 2
    conversation_service.cancel(inventory.stage_id)


async def test_upload_shutdown_purges_partial_intake(conversation_service):
    """Cancelled uploads must remove staged bodies rather than waiting indefinitely."""
    started = asyncio.Event()

    async def chunks():
        yield synthetic_export()[:30]
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(conversation_service.inventory_async(chunks()))
    await asyncio.wait_for(started.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not any(
        path.is_file() for path in conversation_service.staging_root.rglob("*")
    )


def test_restart_expires_abandoned_upload_lease(conversation_service):
    """Abandoned uploading manifests must expire across restarts without exposing bodies."""
    from datetime import UTC, datetime

    path = conversation_service.staging_root / "abandoned-upload"
    path.mkdir(parents=True)
    (path / "export.json").write_bytes(b"UNSELECTED_SECRET_MARKER")
    (path / "upload.json").write_text(
        json.dumps(
            {
                "state": "uploading",
                "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
            }
        )
    )
    result = purge_expired_conversation_stages(conversation_service.staging_root)
    assert result.purged_stage_ids == ["abandoned-upload"]
    assert result.failures == []
    assert not path.exists()


def test_janitor_during_intake_directory_creation_does_not_remove_upload_root(
    conversation_service, monkeypatch
):
    """Removing the shared empty intake root races an uploader about to create its child."""
    original = Path.mkdir

    def interleave(path, *args, **kwargs):
        original(path, *args, **kwargs)
        if path == conversation_service.staging_root / ".intake":
            purge_expired_conversation_stages(conversation_service.staging_root)

    monkeypatch.setattr(Path, "mkdir", interleave)
    inventory = conversation_service.inventory(io.BytesIO(synthetic_export()))
    assert inventory.staging_path.exists()
    conversation_service.cancel(inventory.stage_id)
