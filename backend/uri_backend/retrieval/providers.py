from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

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
