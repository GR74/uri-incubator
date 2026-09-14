from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from contextvars import ContextVar
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from uri_backend.retrieval.providers import (
    EmbeddingBatchError,
    EmbeddingDimensionError,
    GenerationCallMetadata,
    GenerationSpec,
    ProviderConnectionError,
    ProviderError,
    ProviderResponseError,
    ProviderSchemaError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StructuredRequest,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
_TAG_DIGEST = re.compile(r"(?:sha256:)?([0-9a-f]{64})\Z")


class OllamaProvider:
    """Bounded HTTP adapter for a locally configured Ollama instance."""

    def __init__(
        self,
        base_url: str,
        generation_model: str,
        embedding_model: str,
        timeout: float,
        expected_embedding_dimension: int = 384,
        *,
        generation_model_digest: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.generation_model = generation_model
        self.embedding_model = embedding_model
        self.timeout = timeout
        self.expected_embedding_dimension = expected_embedding_dimension
        self.transport = transport
        self._generation_spec = GenerationSpec(
            "ollama",
            generation_model,
            generation_model_digest,
            {"temperature": 0},
            "ollama-chat-v1",
        )
        self._prepared_generation_spec: ContextVar[GenerationSpec] = ContextVar(
            "ollama_prepared_generation_spec", default=self._generation_spec
        )
        self._response_metadata: ContextVar[dict[str, object] | None] = ContextVar(
            "ollama_response_metadata", default=None
        )
        self._generation_metadata: ContextVar[GenerationCallMetadata | None] = ContextVar(
            "ollama_generation_metadata", default=None
        )

    @property
    def generation_spec(self) -> GenerationSpec:
        return self._prepared_generation_spec.get()

    @property
    def last_generation_metadata(self) -> GenerationCallMetadata | None:
        return self._generation_metadata.get()

    @property
    def response_metadata(self) -> dict[str, object] | None:
        metadata = self._response_metadata.get()
        return dict(metadata) if metadata is not None else None

    async def prepare_generation(self) -> GenerationSpec:
        try:
            response = await self._get("/api/tags")
            body = self._decode_response(response)
            models = body.get("models")
            if not isinstance(models, list):
                raise ProviderSchemaError("provider_model_missing")
            matched = next(
                (
                    item
                    for item in models
                    if isinstance(item, dict)
                    and (item.get("name") == self.generation_model or item.get("model") == self.generation_model)
                ),
                None,
            )
            if matched is None:
                raise ProviderSchemaError("provider_model_missing")
            digest = matched.get("digest")
            if not isinstance(digest, str) or (match := _TAG_DIGEST.fullmatch(digest)) is None:
                raise ProviderSchemaError("provider_model_digest_invalid")
            observed_digest = "sha256:" + match.group(1)
            metadata = self.response_metadata or {}
            metadata["observed_digest"] = observed_digest
            self._response_metadata.set(metadata)
            if observed_digest != self._generation_spec.model_digest:
                raise ProviderSchemaError("provider_model_digest_mismatch")
            spec = GenerationSpec(
                self._generation_spec.provider_id,
                self.generation_model,
                observed_digest,
                self._generation_spec.sampling_config,
                self._generation_spec.sampling_version,
            )
            self._prepared_generation_spec.set(spec)
            return spec
        except ProviderError as error:
            self._record_generation_metadata("failed", error.code)
            raise

    async def generate(self, request: StructuredRequest[ModelT]) -> ModelT:
        spec = await self.prepare_generation()
        try:
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
            body = self._decode_response(response)
            if body.get("model") != self.generation_model:
                raise ProviderSchemaError("provider_model_mismatch")
            content = body["message"]["content"]
            payload = json.loads(content)
            result = request.schema.model_validate(payload)
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            error = ProviderSchemaError("provider_invalid_json")
            self._record_generation_metadata("failed", error.code, spec)
            raise error from None
        except ValidationError:
            error = ProviderSchemaError("provider_schema_invalid")
            self._record_generation_metadata("failed", error.code, spec)
            raise error from None
        except ProviderError as error:
            self._record_generation_metadata("failed", error.code, spec)
            raise
        self._record_generation_metadata("succeeded", None, spec)
        return result

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self._post(
            "/api/embed",
            {"model": self.embedding_model, "input": list(texts)},
        )
        try:
            embeddings = self._decode_response(response)["embeddings"]
        except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderSchemaError("provider_invalid_json") from None
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise EmbeddingBatchError()
        if any(
            not isinstance(vector, list)
            or len(vector) != self.expected_embedding_dimension
            or any(
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(float(value))
                for value in vector
            )
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
        self._response_metadata.set({"status_code": response.status_code, "model": payload["model"]})
        return response

    async def _get(self, path: str) -> httpx.Response:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout), transport=self.transport
            ) as client:
                response = await client.get(f"{self.base_url}{path}")
                response.raise_for_status()
        except httpx.TimeoutException:
            raise ProviderTimeoutError() from None
        except httpx.HTTPStatusError as error:
            if error.response.status_code >= 500:
                raise ProviderUnavailableError() from None
            raise ProviderResponseError() from None
        except httpx.TransportError:
            raise ProviderConnectionError() from None
        self._response_metadata.set({"status_code": response.status_code})
        return response

    def _record_generation_metadata(
        self, outcome: str, error_code: str | None, spec: GenerationSpec | None = None
    ) -> None:
        self._generation_metadata.set(
            GenerationCallMetadata.from_spec(
                spec or self.generation_spec,
                self.response_metadata or {},
                outcome=outcome,
                error_code=error_code,
            )
        )

    def _decode_response(self, response: httpx.Response) -> dict[str, object]:
        try:
            body = response.json()
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderSchemaError("provider_invalid_json") from None
        if not isinstance(body, dict):
            raise ProviderSchemaError("provider_invalid_json")
        metadata = self.response_metadata or {}
        for key in (
            "total_duration",
            "load_duration",
            "prompt_eval_count",
            "eval_count",
        ):
            value = body.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                metadata[key] = value
        if isinstance(body.get("done"), bool):
            metadata["done"] = body["done"]
        if isinstance(body.get("created_at"), str):
            metadata["created_at"] = body["created_at"]
        self._response_metadata.set(metadata)
        return body
