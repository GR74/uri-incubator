from __future__ import annotations

import json
from collections.abc import Sequence
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from uri_backend.retrieval.providers import (
    EmbeddingBatchError,
    EmbeddingDimensionError,
    ProviderConnectionError,
    ProviderResponseError,
    ProviderSchemaError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StructuredRequest,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class OllamaProvider:
    """Bounded HTTP adapter for a locally configured Ollama instance."""

    def __init__(
        self,
        base_url: str,
        generation_model: str,
        embedding_model: str,
        timeout: float,
        expected_embedding_dimension: int = 384,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.generation_model = generation_model
        self.embedding_model = embedding_model
        self.timeout = timeout
        self.expected_embedding_dimension = expected_embedding_dimension
        self.transport = transport
        self.response_metadata: dict[str, object] | None = None

    async def generate(self, request: StructuredRequest[ModelT]) -> ModelT:
        response = await self._post(
            "/api/chat",
            {
                "model": self.generation_model,
                "messages": list(request.messages),
                "format": request.schema.model_json_schema(),
                "stream": False,
                "options": {"temperature": 0},
            },
        )
        try:
            content = response.json()["message"]["content"]
            payload = json.loads(content)
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ProviderSchemaError("provider_invalid_json") from None
        try:
            return request.schema.model_validate(payload)
        except ValidationError:
            raise ProviderSchemaError("provider_schema_invalid") from None

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self._post(
            "/api/embed",
            {"model": self.embedding_model, "input": list(texts)},
        )
        try:
            embeddings = response.json()["embeddings"]
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ProviderSchemaError("provider_invalid_json") from None
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingBatchError()
        if any(
            not isinstance(vector, list)
            or len(vector) != self.expected_embedding_dimension
            or any(not isinstance(value, (float, int)) for value in vector)
            for vector in embeddings
        ):
            raise EmbeddingDimensionError()
        return [[float(value) for value in vector] for vector in embeddings]

    async def _post(self, path: str, payload: dict[str, object]) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout), transport=self.transport
            ) as client:
                response = await client.post(f"{self.base_url}{path}", json=payload)
                response.raise_for_status()
        except httpx.TimeoutException:
            raise ProviderTimeoutError() from None
        except httpx.HTTPStatusError as error:
            if error.response.status_code >= 500:
                raise ProviderUnavailableError() from None
            raise ProviderResponseError() from None
        except httpx.TransportError:
            raise ProviderConnectionError() from None
        self.response_metadata = {
            "status_code": response.status_code,
            "model": payload["model"],
            "done": response.headers.get("x-ollama-done") == "true",
        }
        return response
