"""RFC-0017 CA-11 (RFC-0012 3): FakeEmbedder y OpenAIEmbedder pasan la misma
suite de contrato -- las cinco invariantes de la interfaz Embedder. Cualquier
implementacion que se agregue despues entra por esta suite, no por una nueva.

El doble de OpenAIEmbedder deriva su vector de un hash del texto de entrada
(no un vector fijo): sin eso, "el mismo texto produce el mismo vector" seria
verdad para CUALQUIER par de textos, y no probaria nada (RFC-0014 P-1)."""

import hashlib
import math
from collections.abc import Callable

import httpx2
import pytest
from pydantic import SecretStr

from app.retrieval.embedder_fake import FakeEmbedder
from app.retrieval.embedder_openai import OpenAIEmbedder

pytestmark = pytest.mark.unit

_DIMENSION = 1536


def _hash_vector(text: str, dimension: int) -> list[float]:
    seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:4], "big")
    values = [((seed * (i + 1)) % 997) / 997 - 0.5 for i in range(dimension)]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def _openai_mock_handler() -> Callable[[httpx2.Request], httpx2.Response]:
    def handler(request: httpx2.Request) -> httpx2.Response:
        import json

        body = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "embedding": _hash_vector(text, _DIMENSION), "index": i}
                    for i, text in enumerate(body["input"])
                ],
                "model": "text-embedding-3-small",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    return handler


def _make_fake() -> FakeEmbedder:
    return FakeEmbedder(_DIMENSION)


def _make_openai() -> OpenAIEmbedder:
    return OpenAIEmbedder(
        SecretStr("sk-test"),
        "text-embedding-3-small",
        _DIMENSION,
        httpx2.AsyncClient(transport=httpx2.MockTransport(_openai_mock_handler())),
    )


_IMPLEMENTATIONS = {
    "fake": (_make_fake, "fake@test"),
    "openai": (_make_openai, "text-embedding-3-small@openai"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _IMPLEMENTATIONS)
async def test_normalized(name: str) -> None:
    factory, _ = _IMPLEMENTATIONS[name]
    embedder = factory()

    [doc_vector] = await embedder.embed_documents(["un fragmento del CV"])
    query_vector = await embedder.embed_query("una consulta")

    for vector in (doc_vector, query_vector):
        norm = math.sqrt(sum(v * v for v in vector))
        assert abs(norm - 1.0) < 1e-6


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _IMPLEMENTATIONS)
async def test_dimension(name: str) -> None:
    factory, _ = _IMPLEMENTATIONS[name]
    embedder = factory()

    [vector] = await embedder.embed_documents(["texto"])

    assert len(vector) == embedder.dimension == _DIMENSION


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _IMPLEMENTATIONS)
async def test_deterministic(name: str) -> None:
    factory, _ = _IMPLEMENTATIONS[name]
    embedder = factory()

    first = await embedder.embed_query("siempre el mismo texto")
    second = await embedder.embed_query("siempre el mismo texto")

    assert first == second


@pytest.mark.asyncio
@pytest.mark.parametrize("name", _IMPLEMENTATIONS)
async def test_model_id_includes_path(name: str) -> None:
    factory, expected_model_id = _IMPLEMENTATIONS[name]
    embedder = factory()

    assert embedder.model_id == expected_model_id
    assert "@" in embedder.model_id
