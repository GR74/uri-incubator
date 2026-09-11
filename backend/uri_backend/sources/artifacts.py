from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    storage_key: str
    byte_size: int


@dataclass(frozen=True)
class QuarantinedArtifact:
    path: Path
    sha256: str
    byte_size: int


class ArtifactStore(Protocol):
    def put(self, stream: BinaryIO) -> StoredArtifact: ...

    def open(self, sha256: str) -> BinaryIO: ...


class LocalArtifactStore:
    """Filesystem store that publishes only fully-written content-addressed files."""

    def __init__(self, root: Path, staging_root: Path | None = None) -> None:
        self.root = root
        self.staging_root = staging_root or root / "staging"

    def put(self, stream: BinaryIO) -> StoredArtifact:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        byte_size = 0
        staged_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.staging_root, prefix="upload-", delete=False
            ) as staged:
                staged_name = staged.name
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    byte_size += len(chunk)
                    staged.write(chunk)
                self._sync(staged)
            self._publish(staged_name, digest.hexdigest())
            staged_name = None
            return self._stored_artifact(digest, byte_size)
        finally:
            if staged_name is not None:
                Path(staged_name).unlink(missing_ok=True)

    async def put_async(self, stream: AsyncIterator[bytes]) -> StoredArtifact:
        """Stage an ASGI request stream without accumulating its complete body."""
        quarantined = await self.stage_async(stream)
        try:
            return self.promote(quarantined)
        except BaseException:
            self.purge(quarantined)
            raise

    async def stage_async(
        self, stream: AsyncIterator[bytes], max_bytes: int = 16 * 1024 * 1024
    ) -> QuarantinedArtifact:
        """Write a bounded request stream to owner-only quarantine without publishing it."""
        self.staging_root.mkdir(parents=True, exist_ok=True)
        quarantine_root = self.staging_root / "quarantine"
        quarantine_root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        byte_size = 0
        staged_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=quarantine_root, prefix="upload-", delete=False
            ) as staged:
                staged_name = staged.name
                os.chmod(staged_name, 0o600)
                async for incoming in stream:
                    for offset in range(0, len(incoming), 1024 * 1024):
                        chunk = incoming[offset : offset + 1024 * 1024]
                        digest.update(chunk)
                        byte_size += len(chunk)
                        if byte_size > max_bytes:
                            raise ValueError("Upload exceeds the configured size limit.")
                        staged.write(chunk)
                self._sync(staged)
            staged_name = None
            return QuarantinedArtifact(Path(staged.name), digest.hexdigest(), byte_size)
        finally:
            if staged_name is not None:
                Path(staged_name).unlink(missing_ok=True)

    def promote(self, quarantined: QuarantinedArtifact) -> StoredArtifact:
        """Atomically publish a previously validated quarantine file by its hash."""
        self._publish(quarantined.path, quarantined.sha256)
        return StoredArtifact(
            quarantined.sha256,
            f"{quarantined.sha256[:2]}/{quarantined.sha256[2:]}",
            quarantined.byte_size,
        )

    def purge(self, quarantined: QuarantinedArtifact) -> None:
        quarantined.path.unlink(missing_ok=True)

    def _sync(self, staged: BinaryIO) -> None:
        staged.flush()
        os.fsync(staged.fileno())

    def _publish(self, staged_name: str | Path, sha256: str) -> None:
        destination = self.root / sha256[:2] / sha256[2:]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            os.unlink(staged_name)
        else:
            os.replace(staged_name, destination)

    def _stored_artifact(
        self, digest: hashlib._Hash, byte_size: int
    ) -> StoredArtifact:
        sha256 = digest.hexdigest()
        return StoredArtifact(sha256, f"{sha256[:2]}/{sha256[2:]}", byte_size)

    def open(self, sha256: str) -> BinaryIO:
        if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise ValueError("Artifact hash must be a lowercase SHA-256 digest.")
        return (self.root / sha256[:2] / sha256[2:]).open("rb")
