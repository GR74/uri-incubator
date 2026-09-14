from __future__ import annotations

import asyncio
import json
import math

import httpx
import pytest
from pydantic import BaseModel

from tests.fakes import (
    FakeEmbeddingProvider,
    FakeProviderConfigurationError,
    FakeStructuredProvider,
)
from uri_backend.config import Settings
from uri_backend.retrieval.ollama import OllamaProvider
from uri_backend.retrieval.providers import (
    EmbeddingBatchError,
    EmbeddingDimensionError,
    GenerationSpec,
    ProviderConnectionError,
    ProviderSchemaError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    StructuredRequest,
    UnavailableProvider,
    build_model_provider,
)


class CandidateBatch(BaseModel):
    items: list[str]


TEST_DIGEST = "sha256:" + "a" * 64


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
        generation_model_digest=TEST_DIGEST,
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
        generation_model_digest=TEST_DIGEST,
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
    assert provider.response_metadata == {
        "status_code": 200,
        "model": "pilot-model",
        "done": True,
    }
    assert provider.generation_spec.model_digest == TEST_DIGEST
    assert provider.last_generation_metadata is not None
    assert provider.last_generation_metadata.sampling_config == {"temperature": 0}


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


@pytest.mark.parametrize("operation", ["generate", "embed"])
async def test_non_decodable_ollama_response_is_terminal_invalid_json(operation: str) -> None:
    provider = provider_with_response(httpx.Response(200, content=b"\xff"))

    with pytest.raises(ProviderSchemaError) as raised:
        if operation == "generate":
            await provider.generate(StructuredRequest(schema=CandidateBatch, messages=[]))
        else:
            await provider.embed(["one"])

    assert raised.value.code == "provider_invalid_json"
    assert raised.value.retryable is False


async def test_disabled_or_unconfigured_ai_returns_provider_unavailable() -> None:
    provider = FakeStructuredProvider.unavailable()

    with pytest.raises(ProviderUnavailableError) as raised:
        await provider.generate(StructuredRequest(schema=CandidateBatch, messages=[]))

    assert raised.value.code == "provider_unavailable"
    assert Settings().local_ai_enabled is False


async def test_settings_provider_factory_disables_all_transport_attempts() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("disabled provider must not call transport")

    provider = build_model_provider(Settings(), transport=httpx.MockTransport(handler))
    assert isinstance(provider, UnavailableProvider)
    with pytest.raises(ProviderUnavailableError):
        await provider.generate(StructuredRequest(schema=CandidateBatch, messages=[]))
    with pytest.raises(ProviderUnavailableError):
        await provider.embed(["source"])


def test_settings_provider_factory_constructs_ollama_when_enabled() -> None:
    provider = build_model_provider(
        Settings(
            local_ai_enabled=True,
            generation_model="pilot-model",
            generation_model_digest=TEST_DIGEST,
            embedding_model="pilot-embed",
            expected_embedding_dimension=384,
        )
    )
    assert isinstance(provider, OllamaProvider)
    assert provider.expected_embedding_dimension == 384


def test_enabled_local_ai_requires_explicit_models_and_dimension() -> None:
    with pytest.raises(ValueError, match="generation_model"):
        Settings(local_ai_enabled=True)

    settings = Settings(
        local_ai_enabled=True,
        generation_model="pilot-model",
        generation_model_digest=TEST_DIGEST,
        embedding_model="pilot-embed",
        expected_embedding_dimension=384,
    )
    assert settings.expected_embedding_dimension == 384
    with pytest.raises(ValueError, match="generation_model"):
        Settings(
            local_ai_enabled=True,
            generation_model="   ",
            generation_model_digest=TEST_DIGEST,
            embedding_model="pilot-embed",
            expected_embedding_dimension=384,
        )


async def test_fake_structured_provider_requires_explicit_valid_result() -> None:
    with pytest.raises(FakeProviderConfigurationError, match="explicit result"):
        await FakeStructuredProvider().generate(
            StructuredRequest(schema=CandidateBatch, messages=[])
        )


async def test_fake_embeddings_accepts_sequences_and_rejects_nonfinite_values() -> None:
    valid = FakeEmbeddingProvider(expected_dimension=2, responses=[[1, 2.5]])
    assert await valid.embed(("one",)) == [[1.0, 2.5]]
    invalid = FakeEmbeddingProvider(expected_dimension=2, responses=[[math.nan, 1.0]])
    with pytest.raises(EmbeddingDimensionError):
        await invalid.embed(("one",))


async def test_ollama_embeddings_preserve_order_and_normalize_finite_numbers() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={"embeddings": [[1, 2.5], [3.0, 4]], "done": True, "eval_count": 2},
        )

    provider = OllamaProvider(
        "http://127.0.0.1:11434", "pilot-model", "pilot-embed", 30, 2,
        generation_model_digest=TEST_DIGEST,
        transport=httpx.MockTransport(handler),
    )
    result = await provider.embed(("first", "second"))

    assert result == [[1.0, 2.5], [3.0, 4.0]]
    assert json.loads(captured[0].content) == {
        "model": "pilot-embed", "input": ["first", "second"]
    }
    assert provider.response_metadata == {
        "status_code": 200, "model": "pilot-embed", "done": True, "eval_count": 2
    }


async def test_response_metadata_is_task_local_for_shared_provider() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        done = body["messages"][0]["content"] == "complete"
        return httpx.Response(200, json={"message": {"content": '{"items": []}'}, "done": done})

    provider = OllamaProvider(
        "http://127.0.0.1:11434", "pilot-model", "pilot-embed", 30, 2,
        generation_model_digest=TEST_DIGEST,
        transport=httpx.MockTransport(handler),
    )

    async def call(content: str) -> bool:
        await provider.generate(StructuredRequest(schema=CandidateBatch, messages=[{"content": content}]))
        return provider.response_metadata["done"]  # type: ignore[index,return-value]

    assert await asyncio.gather(call("complete"), call("incomplete")) == [True, False]


def test_enabled_local_ai_rejects_noncanonical_generation_digest() -> None:
    with pytest.raises(ValueError, match="canonical sha256"):
        Settings(
            local_ai_enabled=True,
            generation_model="pilot-model",
            generation_model_digest="sha256:pilot",
            embedding_model="pilot-embed",
            expected_embedding_dimension=384,
        )


def test_generation_spec_freezes_effective_sampling_configuration() -> None:
    spec = GenerationSpec(
        "test-provider", "test-model", TEST_DIGEST, {"temperature": 0}, "test-v1"
    )

    with pytest.raises(TypeError):
        spec.sampling_config["temperature"] = 1  # type: ignore[index]
