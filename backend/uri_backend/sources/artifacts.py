from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    storage_key: str
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
                staged.flush()
                os.fsync(staged.fileno())
            sha256 = digest.hexdigest()
            storage_key = f"{sha256[:2]}/{sha256[2:]}"
            destination = self.root / sha256[:2] / sha256[2:]
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                os.unlink(staged_name)
            else:
                os.replace(staged_name, destination)
            staged_name = None
            return StoredArtifact(sha256, storage_key, byte_size)
        finally:
            if staged_name is not None:
                Path(staged_name).unlink(missing_ok=True)

    def open(self, sha256: str) -> BinaryIO:
        if re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise ValueError("Artifact hash must be a lowercase SHA-256 digest.")
        return (self.root / sha256[:2] / sha256[2:]).open("rb")
