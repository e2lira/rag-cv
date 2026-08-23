"""RFC-0017 CA-4/CA-6: OpenAIEmbedder hace una llamada por lote y rechaza
respuestas con dimension inesperada.

Ninguna de estas pruebas llama a la API real (ADR-0012, RFC-0014 P-11): el
transporte HTTP se dobla con httpx2.MockTransport, no OpenAIEmbedder."""

import json
from collections.abc import Callable

import httpx2
import pytest
from pydantic import SecretStr

from app.retrieval.embedder_openai import OpenAIEmbedder

pytestmark = pytest.mark.unit


def _embedding_response(vectors: list[list[float]]) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "object": "list",
            "data": [
                {"object": "embedding", "embedding": vector, "index": i}
                for i, vector in enumerate(vectors)
            ],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        },
    )


def _client(handler: Callable[[httpx2.Request], httpx2.Response]) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def _unit_vector(dimension: int, *, seed: float = 1.0) -> list[float]:
    value = seed / (dimension**0.5)
    return [value] * dimension


@pytest.mark.asyncio
async def test_batches_in_one_call() -> None:
    calls: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        body = json.loads(request.content)
        return _embedding_response([_unit_vector(1536) for _ in body["input"]])

    embedder = OpenAIEmbedder(
        SecretStr("sk-test"), "text-embedding-3-small", 1536, _client(handler)
    )

    vectors = await embedder.embed_documents(["uno", "dos", "tres"])

    assert len(calls) == 1
    body = json.loads(calls[0].content)
    assert body["input"] == ["uno", "dos", "tres"]
    assert len(vectors) == 3


@pytest.mark.asyncio
async def test_rejects_wrong_dimension() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return _embedding_response([_unit_vector(768)])

    embedder = OpenAIEmbedder(
        SecretStr("sk-test"), "text-embedding-3-small", 1536, _client(handler)
    )

    with pytest.raises(ValueError, match="768"):
        await embedder.embed_documents(["texto"])


@pytest.mark.asyncio
async def test_uses_float_encoding_not_default_base64() -> None:
    """La API por defecto devuelve base64 si no se pide 'float' explicito
    (verificado contra el SDK oficial: encoding_format por defecto es
    'base64'). Sin este parametro, embedding vendria como str, no list[float]."""
    captured: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.update(json.loads(request.content))
        return _embedding_response([_unit_vector(1536)])

    embedder = OpenAIEmbedder(
        SecretStr("sk-test"), "text-embedding-3-small", 1536, _client(handler)
    )
    await embedder.embed_documents(["texto"])

    assert captured["encoding_format"] == "float"


@pytest.mark.asyncio
async def test_sends_bearer_authorization() -> None:
    captured_headers: dict[str, str] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured_headers.update(request.headers)
        return _embedding_response([_unit_vector(1536)])

    embedder = OpenAIEmbedder(
        SecretStr("sk-super-secret"), "text-embedding-3-small", 1536, _client(handler)
    )
    await embedder.embed_documents(["texto"])

    assert captured_headers["authorization"] == "Bearer sk-super-secret"
