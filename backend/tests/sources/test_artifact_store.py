from __future__ import annotations

import io
from pathlib import Path

import pytest

from uri_backend.sources.artifacts import LocalArtifactStore


def test_identical_bytes_reuse_one_content_address(tmp_path: Path) -> None:
    """A duplicate payload must never create a filename-derived second object."""
    store = LocalArtifactStore(tmp_path)

    first = store.put(io.BytesIO(b"same evidence"))
    second = store.put(io.BytesIO(b"same evidence"))

    assert first.sha256 == "db30bd9be1a7c28e239aadb67443dab474f93daf4945f4f786013ea66c28a00a"
    assert first.sha256 == second.sha256
    assert first.storage_key == second.storage_key
    assert store.open(first.sha256).read() == b"same evidence"


def test_interrupted_stream_leaves_no_artifact_or_staging_file(tmp_path: Path) -> None:
    """A read failure must not publish partial bytes under a content address."""

    class BrokenStream:
        def __init__(self) -> None:
            self.calls = 0

        def read(self, _: int) -> bytes:
            self.calls += 1
            if self.calls == 1:
                return b"partial"
            raise OSError("interrupted upload")

    store = LocalArtifactStore(tmp_path)
    with pytest.raises(OSError, match="interrupted upload"):
        store.put(BrokenStream())  # type: ignore[arg-type]

    assert list(tmp_path.rglob("*")) == [tmp_path / "staging"]


async def test_async_stream_is_chunked_into_the_content_addressed_staging_file(
    tmp_path: Path,
) -> None:
    """Route-style async input must use the store's staged, bounded intake."""

    async def upload() -> object:
        yield b"a" * (1024 * 1024 + 7)
        yield b"b" * 19

    store = LocalArtifactStore(tmp_path)
    stored = await store.put_async(upload())

    assert stored.storage_key == f"{stored.sha256[:2]}/{stored.sha256[2:]}"
    assert store.open(stored.sha256).read() == b"a" * (1024 * 1024 + 7) + b"b" * 19
