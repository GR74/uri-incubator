from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from uri_backend.retrieval.providers import (
    EmbeddingBatchError,
    EmbeddingDimensionError,
    ProviderUnavailableError,
    StructuredRequest,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class FakeEmbeddingProvider:
    def __init__(self, expected_dimension: int, responses: list[list[float]] | None = None) -> None:
        self.expected_dimension = expected_dimension
        self.responses = responses or []
        self.requests: list[int] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.requests.append(len(texts))
        if len(self.responses) != len(texts):
            raise EmbeddingBatchError()
        if any(
            len(vector) != self.expected_dimension
            or any(
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(float(value))
                for value in vector
            )
            for vector in self.responses
        ):
            raise EmbeddingDimensionError()
        return [[float(value) for value in vector] for vector in self.responses]


class FakeProviderConfigurationError(RuntimeError):
    """Raised when a test fake was not supplied a schema-valid result."""


class FakeStructuredProvider:
    def __init__(self, result: BaseModel | None = None, unavailable: bool = False) -> None:
        self.result = result
        self.is_unavailable = unavailable
        self.requests: list[StructuredRequest[BaseModel]] = []

    @classmethod
    def unavailable(cls) -> FakeStructuredProvider:
        return cls(unavailable=True)

    async def generate(self, request: StructuredRequest[ModelT]) -> ModelT:
        self.requests.append(request)
        if self.is_unavailable:
            raise ProviderUnavailableError()
        if self.result is None:
            raise FakeProviderConfigurationError(
                "FakeStructuredProvider requires an explicit result."
            )
        try:
            return request.schema.model_validate(self.result.model_dump())
        except ValidationError:
            raise FakeProviderConfigurationError(
                "FakeStructuredProvider result is not valid for the requested schema."
            ) from None
