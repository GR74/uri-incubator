from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

import httpx
from pydantic import BaseModel

if TYPE_CHECKING:
    from uri_backend.config import Settings
    from uri_backend.retrieval.ollama import OllamaProvider

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class StructuredRequest(Generic[ModelT]):
    """A schema-bound local-model request with caller-owned messages."""

    schema: type[ModelT]
    messages: Sequence[dict[str, object]]


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding per input, in input order."""


class StructuredGenerationProvider(Protocol):
    async def generate(self, request: StructuredRequest[ModelT]) -> ModelT:
        """Generate and validate one schema-conforming response."""


class ProviderError(RuntimeError):
    code = "provider_error"
    retryable = False

    def __init__(self) -> None:
        super().__init__(self.code)


class ProviderUnavailableError(ProviderError):
    code = "provider_unavailable"
    retryable = True


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"
    retryable = True


class ProviderConnectionError(ProviderError):
    code = "provider_connection"
    retryable = True


class ProviderResponseError(ProviderError):
    code = "provider_response_invalid"


class ProviderSchemaError(ProviderError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__()


class EmbeddingBatchError(ProviderError):
    code = "embedding_batch_mismatch"


class EmbeddingDimensionError(ProviderError):
    code = "embedding_dimension_mismatch"


class UnavailableProvider:
    """Safe disabled-provider implementation for unconfigured local AI."""

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise ProviderUnavailableError()

    async def generate(self, request: StructuredRequest[ModelT]) -> ModelT:
        raise ProviderUnavailableError()


def build_model_provider(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> OllamaProvider | UnavailableProvider:
    """Select the disabled-safe provider or a configured Ollama adapter."""
    if not settings.local_ai_enabled:
        return UnavailableProvider()
    from uri_backend.retrieval.ollama import OllamaProvider

    assert settings.generation_model is not None
    assert settings.embedding_model is not None
    assert settings.expected_embedding_dimension is not None
    return OllamaProvider(
        base_url=settings.ollama_base_url,
        generation_model=settings.generation_model,
        embedding_model=settings.embedding_model,
        timeout=settings.ollama_timeout_seconds,
        expected_embedding_dimension=settings.expected_embedding_dimension,
        transport=transport,
    )
