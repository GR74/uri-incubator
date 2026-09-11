from __future__ import annotations

from typing import Protocol

from uri_backend.ingestion.contracts import AdapterInput, NormalizationResult


class SourceAdapter(Protocol):
    def supports(self, context: AdapterInput) -> bool: ...

    def normalize(self, context: AdapterInput) -> NormalizationResult: ...


class AdapterRegistry:
    def __init__(self, adapters: list[SourceAdapter] | None = None) -> None:
        self._adapters = adapters or []

    def register(self, adapter: SourceAdapter) -> None:
        self._adapters.append(adapter)

    def resolve(self, family: str, media_type: str) -> SourceAdapter:
        context = AdapterInput(artifact_path=".", family=family, media_type=media_type)
        for adapter in self._adapters:
            if adapter.supports(context):
                return adapter
        raise LookupError(f"No adapter for family {family!r} and media type {media_type!r}")
