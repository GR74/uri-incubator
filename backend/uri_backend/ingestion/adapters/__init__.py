"""Deterministic source normalization adapters."""

from uri_backend.ingestion.adapters.base import AdapterRegistry, SourceAdapter
from uri_backend.ingestion.adapters.conversations import (
    ConversationAdapter,
    ConversationService,
)
from uri_backend.ingestion.adapters.documents import DocumentAdapter
from uri_backend.ingestion.adapters.git import GitAdapter
from uri_backend.ingestion.adapters.lab_notebooks import LabNotebookAdapter
from uri_backend.ingestion.adapters.manifests import ManifestAdapter
from uri_backend.ingestion.adapters.notebooks import NotebookAdapter

__all__ = [
    "AdapterRegistry",
    "ConversationAdapter",
    "ConversationService",
    "DocumentAdapter",
    "GitAdapter",
    "LabNotebookAdapter",
    "ManifestAdapter",
    "NotebookAdapter",
    "SourceAdapter",
]
