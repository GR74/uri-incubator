from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar

import httpx
from pydantic import BaseModel

if TYPE_CHECKING:
    from uri_backend.config import Settings
    from uri_backend.retrieval.ollama import OllamaProvider

ModelT = TypeVar("ModelT", bound=BaseModel)
_MODEL_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def _freeze_json(value: object) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("generation metadata keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("generation metadata must be JSON-compatible")


def generation_json(value: object) -> object:
    """Return a detached plain JSON-compatible value for durable provenance."""
    if isinstance(value, Mapping):
        return {key: generation_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [generation_json(item) for item in value]
    return value


@dataclass(frozen=True)
class GenerationSpec:
    """Provider-declared immutable identity and effective generation settings."""

    provider_id: str
    model_id: str
    model_digest: str
    sampling_config: Mapping[str, object]
    sampling_version: str

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.model_id.strip() or not self.sampling_version.strip():
            raise ValueError("generation identity fields must be nonblank")
        if _MODEL_DIGEST.fullmatch(self.model_digest) is None:
            raise ValueError("model_digest must be canonical sha256:<64 lowercase hex>")
        frozen = _freeze_json(self.sampling_config)
        assert isinstance(frozen, Mapping)
        object.__setattr__(self, "sampling_config", frozen)


@dataclass(frozen=True)
class GenerationCallMetadata:
    """Task-local metadata for one actual structured-generation request."""

    provider_id: str
    model_id: str
    model_digest: str
    sampling_config: Mapping[str, object]
    sampling_version: str
    response_metadata: Mapping[str, object]
    outcome: str = "succeeded"
    error_code: str | None = None

    def __post_init__(self) -> None:
        sampling = _freeze_json(self.sampling_config)
        response = _freeze_json(self.response_metadata)
        assert isinstance(sampling, Mapping) and isinstance(response, Mapping)
        object.__setattr__(self, "sampling_config", sampling)
        object.__setattr__(self, "response_metadata", response)

    @classmethod
    def from_spec(
        cls,
        spec: GenerationSpec,
        response_metadata: Mapping[str, object],
        *,
        outcome: str = "succeeded",
        error_code: str | None = None,
    ) -> GenerationCallMetadata:
        return cls(
            provider_id=spec.provider_id,
            model_id=spec.model_id,
            model_digest=spec.model_digest,
            sampling_config=spec.sampling_config,
            sampling_version=spec.sampling_version,
            response_metadata=response_metadata,
            outcome=outcome,
            error_code=error_code,
        )


@dataclass(frozen=True)
class StructuredRequest(Generic[ModelT]):
    """A schema-bound local-model request with caller-owned messages."""

    schema: type[ModelT]
    messages: Sequence[dict[str, object]]


class EmbeddingProvider(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding per input, in input order."""


class StructuredGenerationProvider(Protocol):
    async def prepare_generation(self) -> GenerationSpec:
        """Verify and return identity/settings before a generation attempt."""

    @property
    def generation_spec(self) -> GenerationSpec:
        """Identity and settings the provider will actually apply to generation."""

    @property
    def last_generation_metadata(self) -> GenerationCallMetadata | None:
        """Task-local metadata from the most recent generate call."""

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

    _generation_spec = GenerationSpec(
        "unavailable", "unavailable", "sha256:" + "0" * 64, {}, "unavailable-v1"
    )

    @property
    def generation_spec(self) -> GenerationSpec:
        return self._generation_spec

    @property
    def last_generation_metadata(self) -> GenerationCallMetadata | None:
        return None

    async def prepare_generation(self) -> GenerationSpec:
        return self._generation_spec

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
        generation_model_digest=settings.generation_model_digest,
        transport=transport,
    )
