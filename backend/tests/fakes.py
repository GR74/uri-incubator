from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.requests.append(len(texts))
        if len(self.responses) != len(texts):
            raise EmbeddingBatchError()
        if any(len(vector) != self.expected_dimension for vector in self.responses):
            raise EmbeddingDimensionError()
        return [list(vector) for vector in self.responses]


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
            return request.schema.model_construct()
        return request.schema.model_validate(self.result.model_dump())
