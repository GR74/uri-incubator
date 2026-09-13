from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from tests.fakes import FakeEmbeddingProvider, FakeStructuredProvider
from uri_backend.config import Settings
from uri_backend.retrieval.ollama import OllamaProvider
from uri_backend.retrieval.providers import (
    EmbeddingBatchError,
    EmbeddingDimensionError,
    ProviderConnectionError,
    ProviderSchemaError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StructuredRequest,
)


class CandidateBatch(BaseModel):
    items: list[str]


def provider_with_response(response: httpx.Response | Exception) -> OllamaProvider:
    async def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    return OllamaProvider(
        base_url="http://127.0.0.1:11434",
        generation_model="pilot-model",
        embedding_model="pilot-embed",
        timeout=30,
        expected_embedding_dimension=2,
        transport=httpx.MockTransport(handler),
    )


async def test_ollama_structured_generation_sends_exact_json_schema() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"message": {"content": '{"items": []}'}, "done": True})

    provider = OllamaProvider(
        base_url="http://127.0.0.1:11434",
        generation_model="pilot-model",
        embedding_model="pilot-embed",
        timeout=30,
        expected_embedding_dimension=2,
        transport=httpx.MockTransport(handler),
    )

    result = await provider.generate(StructuredRequest(schema=CandidateBatch, messages=[]))

    assert result == CandidateBatch(items=[])
    assert len(captured) == 1
    body = json.loads(captured[0].content)
    assert captured[0].url == "http://127.0.0.1:11434/api/chat"
    assert body == {
        "model": "pilot-model",
        "messages": [],
        "format": CandidateBatch.model_json_schema(),
        "stream": False,
        "options": {"temperature": 0},
    }


async def test_embedding_dimension_mismatch_is_rejected() -> None:
    provider = FakeEmbeddingProvider(expected_dimension=2, responses=[[0.0, 1.0], [1.0]])

    with pytest.raises(EmbeddingDimensionError) as raised:
        await provider.embed(["a", "b"])

    assert raised.value.code == "embedding_dimension_mismatch"
    assert "source text" not in str(raised.value)


async def test_embedding_batch_mismatch_is_rejected_without_source_text() -> None:
    provider = FakeEmbeddingProvider(expected_dimension=2, responses=[[0.0, 1.0]])

    with pytest.raises(EmbeddingBatchError) as raised:
        await provider.embed(["confidential source", "second source"])

    assert raised.value.code == "embedding_batch_mismatch"
    assert "confidential" not in str(raised.value)


async def test_ollama_timeout_and_connection_errors_are_retryable() -> None:
    timeout = provider_with_response(httpx.ReadTimeout("timed out"))
    connection = provider_with_response(httpx.ConnectError("offline"))

    with pytest.raises(ProviderTimeoutError) as timeout_error:
        await timeout.generate(StructuredRequest(schema=CandidateBatch, messages=[]))
    with pytest.raises(ProviderConnectionError) as connection_error:
        await connection.generate(StructuredRequest(schema=CandidateBatch, messages=[]))

    assert timeout_error.value.retryable is True
    assert connection_error.value.retryable is True


async def test_invalid_json_and_schema_are_terminal() -> None:
    invalid_json = provider_with_response(httpx.Response(200, json={"message": {"content": "nope"}}))
    invalid_schema = provider_with_response(httpx.Response(200, json={"message": {"content": '{"items": [1]}'}}))

    with pytest.raises(ProviderSchemaError) as json_error:
        await invalid_json.generate(StructuredRequest(schema=CandidateBatch, messages=[]))
    with pytest.raises(ProviderSchemaError) as schema_error:
        await invalid_schema.generate(StructuredRequest(schema=CandidateBatch, messages=[]))

    assert json_error.value.code == "provider_invalid_json"
    assert schema_error.value.code == "provider_schema_invalid"
    assert json_error.value.retryable is False
    assert schema_error.value.retryable is False


async def test_disabled_or_unconfigured_ai_returns_provider_unavailable() -> None:
    provider = FakeStructuredProvider.unavailable()

    with pytest.raises(ProviderUnavailableError) as raised:
        await provider.generate(StructuredRequest(schema=CandidateBatch, messages=[]))

    assert raised.value.code == "provider_unavailable"
    assert Settings().local_ai_enabled is False


def test_enabled_local_ai_requires_explicit_models_and_dimension() -> None:
    with pytest.raises(ValueError, match="generation_model"):
        Settings(local_ai_enabled=True)

    settings = Settings(
        local_ai_enabled=True,
        generation_model="pilot-model",
        embedding_model="pilot-embed",
        expected_embedding_dimension=384,
    )
    assert settings.expected_embedding_dimension == 384
