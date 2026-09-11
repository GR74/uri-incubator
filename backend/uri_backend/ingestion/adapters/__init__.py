"""Deterministic source normalization adapters."""

from uri_backend.ingestion.adapters.base import AdapterRegistry, SourceAdapter
from uri_backend.ingestion.adapters.documents import DocumentAdapter

__all__ = ["AdapterRegistry", "DocumentAdapter", "SourceAdapter"]
