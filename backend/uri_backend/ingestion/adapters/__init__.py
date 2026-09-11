"""Deterministic source normalization adapters."""

from uri_backend.ingestion.adapters.base import AdapterRegistry, SourceAdapter
from uri_backend.ingestion.adapters.conversations import ConversationService
from uri_backend.ingestion.adapters.documents import DocumentAdapter
from uri_backend.ingestion.adapters.git import GitAdapter

__all__ = ["AdapterRegistry", "ConversationService", "DocumentAdapter", "GitAdapter", "SourceAdapter"]
