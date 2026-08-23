"""RFC-0017 CA-4/CA-6/CA-13: OpenAIEmbedder hace una llamada por lote, rechaza
respuestas con dimension inesperada o cardinalidad incorrecta, y ordena por
data[].index en vez de confiar en el orden de llegada -- el SDK oficial de
OpenAI NO reordena (verificado en su codigo fuente), asi que este contrato es
mas estricto que el del cliente de referencia, a proposito (RFC-0017 A-18).

Ninguna de estas pruebas llama a la API real (ADR-0012, RFC-0014 P-11): el
transporte HTTP se dobla con httpx2.MockTransport, no OpenAIEmbedder."""

import json
from collections.abc import Callable

import httpx2
import pytest
from pydantic import SecretStr

from app.retrieval.embedder_openai import OpenAIEmbedder

pytestmark = pytest.mark.unit


def _embedding_response(
    vectors: list[list[float]], *, indices: list[int] | None = None
) -> httpx2.Response:
    order = indices if indices is not None else list(range(len(vectors)))
    return httpx2.Response(
        200,
        json={
            "object": "list",
            "data": [
                {"object": "embedding", "embedding": vector, "index": index}
                for vector, index in zip(vectors, order, strict=True)
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


def _distinct_vector(dimension: int, marker: float) -> list[float]:
    """Vector cuya direccion depende de `marker`: a diferencia de
    _unit_vector, dos markers distintos siguen siendo distinguibles despues
    de normalizar -- necesario para probar que el reordenamiento asocia el
    vector correcto, no solo que produce ALGUN vector."""
    vector = [1.0] * dimension
    vector[0] = marker
    return vector


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
async def test_rejects_wrong_cardinality() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        # Tres textos pedidos, solo dos vectores en la respuesta.
        return _embedding_response([_unit_vector(1536), _unit_vector(1536)])

    embedder = OpenAIEmbedder(
        SecretStr("sk-test"), "text-embedding-3-small", 1536, _client(handler)
    )

    with pytest.raises(ValueError, match="3.*2|2.*3"):
        await embedder.embed_documents(["uno", "dos", "tres"])


@pytest.mark.asyncio
async def test_reorders_by_index() -> None:
    """La respuesta llega desordenada (indice 2, luego 0, luego 1); el vector
    en la posicion i del resultado debe ser el de indice i, no el i-esimo en
    llegar. El SDK oficial de OpenAI no hace esta comprobacion -- este
    contrato es mas estricto a proposito (RFC-0017 A-18)."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        vectors = [_distinct_vector(1536, marker) for marker in (10.0, 20.0, 30.0)]
        shuffled_vectors = [vectors[2], vectors[0], vectors[1]]
        shuffled_indices = [2, 0, 1]
        return _embedding_response(shuffled_vectors, indices=shuffled_indices)

    embedder = OpenAIEmbedder(
        SecretStr("sk-test"), "text-embedding-3-small", 1536, _client(handler)
    )

    result = await embedder.embed_documents(["texto-0", "texto-1", "texto-2"])

    expected = [_distinct_vector(1536, marker) for marker in (10.0, 20.0, 30.0)]
    for position, marker_vector in enumerate(expected):
        norm = sum(c * c for c in marker_vector) ** 0.5
        assert result[position] == pytest.approx([c / norm for c in marker_vector])


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
