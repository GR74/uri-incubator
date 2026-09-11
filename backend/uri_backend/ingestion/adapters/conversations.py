from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uri_backend.ingestion.contracts import (
    AdapterInput,
    NormalizationResult,
    NormalizationWarning,
    NormalizedPart,
)
from uri_backend.projects.models import AuditEvent, Project, User
from uri_backend.sources.artifacts import LocalArtifactStore
from uri_backend.sources.models import SourceVersion
from uri_backend.sources.schemas import RegisterSourceVersion
from uri_backend.sources.service import register_source_version

CONVERSATION_MEDIA_TYPE = "application/vnd.uri.conversation+json"
MAX_EXPORT_BYTES = 16 * 1024 * 1024
MAX_CONVERSATIONS = 1_000
MAX_MESSAGES_PER_CONVERSATION = 10_000
MAX_NESTING = 100


class ConversationAdapter:
    """Normalize only the already-selected canonical conversation artifact."""

    name = "conversation"
    version = "normalization-v1"

    def supports(self, context: AdapterInput) -> bool:
        return (
            context.family == "conversation"
            and context.media_type == CONVERSATION_MEDIA_TYPE
        )

    def normalize(self, context: AdapterInput) -> NormalizationResult:
        if not self.supports(context):
            return self._result("unsupported", [], "unsupported_conversation")
        try:
            payload = json.loads(context.artifact_path.read_text(encoding="utf-8"))
            conversation_id = payload["conversation_id"]
            messages = payload["messages"]
            if not isinstance(conversation_id, str) or not isinstance(messages, list):
                raise TypeError("invalid canonical conversation")
            parts = [
                NormalizedPart(
                    ordinal=int(message["ordinal"]),
                    kind="message",
                    text=str(message["text"]),
                    locator={
                        "conversation_id": conversation_id,
                        "message_id": str(message["message_id"]),
                        "node_id": str(message["node_id"]),
                    },
                    author_label=message.get("author_label")
                    if isinstance(message.get("author_label"), str)
                    else None,
                    source_time=datetime.fromisoformat(message["timestamp"])
                    if isinstance(message.get("timestamp"), str)
                    else None,
                    metadata={"role": str(message["role"])},
                )
                for message in messages
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._result("failed", [], "parse_error")
        return NormalizationResult(
            adapter=self.name,
            adapter_version=self.version,
            status="normalized",
            parts=parts,
            parse_coverage=1.0,
        )

    def _result(
        self, status: str, parts: list[NormalizedPart], warning_code: str
    ) -> NormalizationResult:
        return NormalizationResult(
            adapter=self.name,
            adapter_version=self.version,
            status=status,  # type: ignore[arg-type]
            parts=parts,
            warnings=[
                NormalizationWarning(
                    code=warning_code,
                    message="Conversation normalization could not complete.",
                )
            ],
            parse_coverage=0.0,
        )


class ConversationStageError(Exception):
    """A safe, content-free error from temporary conversation staging."""


class ExportMalformed(ConversationStageError):
    pass


class StageExpired(ConversationStageError):
    pass


class UnknownConversation(ConversationStageError):
    pass


class StagePurgeFailed(ConversationStageError):
    pass


class ConversationInventoryItem(BaseModel):
    external_id: str
    title: str | None
    created_at: datetime | None
    updated_at: datetime | None
    message_count: int


class StagedConversationInventory(BaseModel):
    stage_id: str
    conversations: list[ConversationInventoryItem]
    expires_at: datetime
    staging_path: Path


@dataclass(frozen=True)
class StageCleanupResult:
    purged_stage_ids: list[str]
    failures: list[str]


@dataclass(frozen=True)
class _Stage:
    inventory: StagedConversationInventory
    export_hash: str


def _safe_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ExportMalformed("Conversation export has an unsupported timestamp.")
    return datetime.fromtimestamp(value, tz=UTC)


def _validate_nesting(value: object, depth: int = 0) -> None:
    if depth > MAX_NESTING:
        raise ExportMalformed("Conversation export nesting exceeds the allowed limit.")
    if isinstance(value, dict):
        for child in value.values():
            _validate_nesting(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_nesting(child, depth + 1)


def _conversation_messages(conversation: dict[str, object]) -> list[dict[str, object]]:
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        raise ExportMalformed(
            "Conversation export has an unsupported conversation shape."
        )
    current = conversation.get("current_node")
    nodes: list[dict[str, object]] = []
    if isinstance(current, str):
        seen: set[str] = set()
        while current is not None:
            if current in seen or len(seen) >= MAX_MESSAGES_PER_CONVERSATION:
                raise ExportMalformed(
                    "Conversation export has an invalid message graph."
                )
            seen.add(current)
            node = mapping.get(current)
            if not isinstance(node, dict):
                raise ExportMalformed(
                    "Conversation export has an invalid message graph."
                )
            nodes.append(node)
            parent = node.get("parent")
            if parent is not None and not isinstance(parent, str):
                raise ExportMalformed(
                    "Conversation export has an invalid message graph."
                )
            current = parent
        nodes.reverse()
    else:
        nodes = [node for node in mapping.values() if isinstance(node, dict)]
    messages: list[dict[str, object]] = []
    for node in nodes:
        message = node.get("message")
        if message is None:
            continue
        if not isinstance(message, dict):
            raise ExportMalformed(
                "Conversation export has an unsupported message shape."
            )
        author = message.get("author")
        content = message.get("content")
        if not isinstance(author, dict) or not isinstance(content, dict):
            raise ExportMalformed(
                "Conversation export has an unsupported message shape."
            )
        role = author.get("role")
        parts = content.get("parts")
        if (
            not isinstance(role, str)
            or not isinstance(parts, list)
            or not all(isinstance(part, str) for part in parts)
        ):
            raise ExportMalformed(
                "Conversation export has an unsupported message shape."
            )
        message_id = message.get("id")
        node_id = node.get("id")
        parent_id = node.get("parent")
        if (
            not isinstance(message_id, str)
            or not isinstance(node_id, str)
            or (parent_id is not None and not isinstance(parent_id, str))
        ):
            raise ExportMalformed(
                "Conversation export has an unsupported message shape."
            )
        messages.append(
            {
                "ordinal": len(messages) + 1,
                "role": role,
                "author_label": author.get("name")
                if isinstance(author.get("name"), str)
                else None,
                "timestamp": _safe_datetime(message.get("create_time")),
                "message_id": message_id,
                "parent_id": parent_id,
                "node_id": node_id,
                "text": "\n".join(parts),
            }
        )
    return messages


def _parse_export(
    raw: bytes,
) -> tuple[list[dict[str, object]], list[ConversationInventoryItem]]:
    try:
        decoded = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExportMalformed("Conversation export is not valid JSON.") from error
    _validate_nesting(decoded)
    if not isinstance(decoded, list) or len(decoded) > MAX_CONVERSATIONS:
        raise ExportMalformed("Conversation export has an unsupported top-level shape.")
    conversations: list[dict[str, object]] = []
    inventory: list[ConversationInventoryItem] = []
    seen_ids: set[str] = set()
    for conversation in decoded:
        if not isinstance(conversation, dict):
            raise ExportMalformed(
                "Conversation export has an unsupported conversation shape."
            )
        external_id = conversation.get("id")
        if (
            not isinstance(external_id, str)
            or not external_id
            or external_id in seen_ids
        ):
            raise ExportMalformed(
                "Conversation export has an invalid conversation identifier."
            )
        seen_ids.add(external_id)
        title = conversation.get("title")
        if title is not None and not isinstance(title, str):
            raise ExportMalformed("Conversation export has an unsupported title.")
        messages = _conversation_messages(conversation)
        if len(messages) > MAX_MESSAGES_PER_CONVERSATION:
            raise ExportMalformed("Conversation export exceeds the message limit.")
        conversations.append(conversation)
        inventory.append(
            ConversationInventoryItem(
                external_id=external_id,
                title=title,
                created_at=_safe_datetime(conversation.get("create_time")),
                updated_at=_safe_datetime(conversation.get("update_time")),
                message_count=len(messages),
            )
        )
    return conversations, inventory


class ConversationService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        artifact_store: LocalArtifactStore,
        staging_root: Path,
        actor_id: UUID,
        project_id: UUID,
    ) -> None:
        self.session_factory = session_factory
        self.artifact_store = artifact_store
        self.staging_root = staging_root
        self.actor_id = actor_id
        self.project_id = project_id
        self._stages: dict[str, _Stage] = {}

    def inventory(
        self, stream: BinaryIO, ttl: timedelta = timedelta(minutes=15)
    ) -> StagedConversationInventory:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.staging_root, 0o700)
        stage_id = secrets.token_urlsafe(24)
        staging_path = self.staging_root / stage_id
        staging_path.mkdir(mode=0o700)
        export_path = staging_path / "export.json"
        digest = hashlib.sha256()
        byte_size = 0
        try:
            with export_path.open("xb") as output:
                os.chmod(export_path, 0o600)
                while chunk := stream.read(1024 * 1024):
                    byte_size += len(chunk)
                    if byte_size > MAX_EXPORT_BYTES:
                        raise ExportMalformed(
                            "Conversation export exceeds the byte limit."
                        )
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            return self._finalize_inventory(stage_id, staging_path, digest, ttl)
        except Exception:
            self._purge_path(staging_path)
            raise

    async def inventory_async(
        self, stream: AsyncIterator[bytes], ttl: timedelta = timedelta(minutes=15)
    ) -> StagedConversationInventory:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.staging_root, 0o700)
        stage_id = secrets.token_urlsafe(24)
        staging_path = self.staging_root / stage_id
        staging_path.mkdir(mode=0o700)
        export_path = staging_path / "export.json"
        digest = hashlib.sha256()
        byte_size = 0
        try:
            with export_path.open("xb") as output:
                os.chmod(export_path, 0o600)
                async for incoming in stream:
                    for offset in range(0, len(incoming), 1024 * 1024):
                        chunk = incoming[offset : offset + 1024 * 1024]
                        byte_size += len(chunk)
                        if byte_size > MAX_EXPORT_BYTES:
                            raise ExportMalformed(
                                "Conversation export exceeds the byte limit."
                            )
                        digest.update(chunk)
                        output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            return self._finalize_inventory(stage_id, staging_path, digest, ttl)
        except Exception:
            self._purge_path(staging_path)
            raise

    def _finalize_inventory(
        self, stage_id: str, staging_path: Path, digest: object, ttl: timedelta
    ) -> StagedConversationInventory:
        _, conversations = _parse_export((staging_path / "export.json").read_bytes())
        inventory = StagedConversationInventory(
            stage_id=stage_id,
            conversations=conversations,
            expires_at=datetime.now(UTC) + ttl,
            staging_path=staging_path,
        )
        stage = _Stage(inventory, digest.hexdigest())
        self._write_manifest(stage)
        self._stages[stage_id] = stage
        return inventory

    def _write_manifest(self, stage: _Stage) -> None:
        manifest_path = stage.inventory.staging_path / "stage.json"
        payload = {
            "stage_id": stage.inventory.stage_id,
            "actor_id": str(self.actor_id),
            "project_id": str(self.project_id),
            "expires_at": stage.inventory.expires_at.isoformat(),
            "source_export_sha256": stage.export_hash,
            "conversations": [
                item.model_dump(mode="json") for item in stage.inventory.conversations
            ],
        }
        with manifest_path.open("x", encoding="utf-8") as output:
            os.chmod(manifest_path, 0o600)
            json.dump(payload, output, ensure_ascii=True, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())

    def _stage(self, stage_id: str) -> _Stage | None:
        cached = self._stages.get(stage_id)
        if cached is not None:
            return cached
        if Path(stage_id).name != stage_id:
            return None
        staging_path = self.staging_root / stage_id
        manifest_path = staging_path / "stage.json"
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                payload["stage_id"] != stage_id
                or UUID(payload["actor_id"]) != self.actor_id
                or UUID(payload["project_id"]) != self.project_id
            ):
                return None
            inventory = StagedConversationInventory(
                stage_id=stage_id,
                conversations=[
                    ConversationInventoryItem.model_validate(item)
                    for item in payload["conversations"]
                ],
                expires_at=datetime.fromisoformat(payload["expires_at"]),
                staging_path=staging_path,
            )
            stage = _Stage(inventory, str(payload["source_export_sha256"]))
            self._stages[stage_id] = stage
            return stage
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def cancel(self, stage_id: str) -> None:
        stage = self._stage(stage_id)
        if stage is not None:
            self._purge_path(stage.inventory.staging_path)
            self._stages.pop(stage_id, None)

    async def promote(
        self, stage_id: str, conversation_ids: list[str]
    ) -> list[SourceVersion]:
        stage = self._stage(stage_id)
        if stage is None:
            raise UnknownConversation("Conversation stage was not found.")
        if datetime.now(UTC) >= stage.inventory.expires_at:
            self.cancel(stage_id)
            raise StageExpired("Conversation stage has expired.")
        selected = list(dict.fromkeys(conversation_ids))
        available = {item.external_id for item in stage.inventory.conversations}
        if not set(selected).issubset(available):
            self.cancel(stage_id)
            raise UnknownConversation(
                "Selected conversation was not found in this stage."
            )
        if not selected:
            self.cancel(stage_id)
            return []
        try:
            raw = (stage.inventory.staging_path / "export.json").read_bytes()
            conversations, _ = _parse_export(raw)
            by_id = {conversation["id"]: conversation for conversation in conversations}
            async with self.session_factory() as session:
                actor = await session.get(User, self.actor_id)
                project = await session.get(Project, self.project_id)
                if actor is None or project is None:
                    raise UnknownConversation(
                        "Conversation promotion context was not found."
                    )
                versions: list[SourceVersion] = []
                for external_id in selected:
                    conversation = by_id[external_id]
                    canonical = self._canonical_conversation(
                        conversation, stage.export_hash
                    )
                    stored = self.artifact_store.put(BytesIO(canonical))
                    version = await register_source_version(
                        session,
                        actor,
                        RegisterSourceVersion(
                            project_id=project.id,
                            family="conversation",
                            external_id=external_id,
                            native_version=f"chatgpt-export:{stage.export_hash}:{external_id}",
                            media_type=CONVERSATION_MEDIA_TYPE,
                            title=conversation.get("title")
                            if isinstance(conversation.get("title"), str)
                            else None,
                            metadata={"source_export_sha256": stage.export_hash},
                        ),
                        stored,
                    )
                    versions.append(version)
                session.add(
                    AuditEvent(
                        actor_id=actor.id,
                        project_id=project.id,
                        action="conversation.stage_promoted",
                        target_type="conversation_stage",
                        target_id=uuid4(),
                        metadata_={
                            "selected_conversation_ids": selected,
                            "source_export_sha256": stage.export_hash,
                        },
                    )
                )
                await session.commit()
            self.cancel(stage_id)
            return versions
        except Exception:
            self.cancel(stage_id)
            raise

    def _canonical_conversation(
        self, conversation: dict[str, object], export_hash: str
    ) -> bytes:
        messages = _conversation_messages(conversation)
        payload = {
            "conversation_id": conversation["id"],
            "title": conversation.get("title"),
            "created_at": _timestamp_json(conversation.get("create_time")),
            "updated_at": _timestamp_json(conversation.get("update_time")),
            "source_export_sha256": export_hash,
            "messages": [
                {**message, "timestamp": _timestamp_json(message["timestamp"])}
                for message in messages
            ],
        }
        return json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def _purge_path(self, staging_path: Path) -> None:
        try:
            shutil.rmtree(staging_path)
        except FileNotFoundError:
            return
        except OSError as error:
            raise StagePurgeFailed("Conversation staging purge failed.") from error


def _timestamp_json(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return _safe_datetime(value).isoformat()


def purge_expired_conversation_stages(staging_root: Path) -> StageCleanupResult:
    """Purge expired or unreadable stage directories without exposing export contents."""
    purged: list[str] = []
    failures: list[str] = []
    if not staging_root.exists():
        return StageCleanupResult(purged, failures)
    try:
        stage_paths = list(staging_root.iterdir())
    except OSError:
        return StageCleanupResult(purged, ["staging_root"])
    for staging_path in stage_paths:
        if not staging_path.is_dir():
            continue
        try:
            payload = json.loads(
                (staging_path / "stage.json").read_text(encoding="utf-8")
            )
            expires_at = datetime.fromisoformat(payload["expires_at"])
            expired = datetime.now(UTC) >= expires_at
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            expired = True
        if not expired:
            continue
        try:
            shutil.rmtree(staging_path)
            purged.append(staging_path.name)
        except OSError:
            failures.append(staging_path.name)
    return StageCleanupResult(purged, failures)


async def promote_selected_conversations(
    stage_id: str,
    conversation_ids: list[str],
    actor: User,
    project: Project,
    *,
    service: ConversationService,
) -> list[SourceVersion]:
    """Promote an explicitly selected durable stage for its authorized actor/project."""
    if service.actor_id != actor.id or service.project_id != project.id:
        raise UnknownConversation("Conversation stage was not found.")
    return await service.promote(stage_id, conversation_ids)


def stage_conversation_export(
    stream: BinaryIO, staging_root: Path, ttl: timedelta
) -> StagedConversationInventory:
    """Stage and inspect an export without creating any durable source artifact."""
    service = ConversationService(
        async_sessionmaker(),
        LocalArtifactStore(staging_root / "unused"),
        staging_root,
        uuid4(),
        uuid4(),
    )
    return service.inventory(stream, ttl)
