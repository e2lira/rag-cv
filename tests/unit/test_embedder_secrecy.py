"""RFC-0017 CA-12: la clave de OpenAIEmbedder nunca aparece en repr(), str()
ni en el mensaje de una excepcion -- mismo criterio que T-9 de la rubrica
transversal, aplicado a la capa de embeddings en vez de a Settings.

Esto NO es un criterio heredado de RFC-0014 6.1.2: OpenAIEmbedder es codigo
nuevo de este PR (creado en 8d463e9), no una implementacion de un RFC
anterior ya fusionada sin cambios -- T-9 es la rubrica transversal que exige
el patron, pero aplicarlo aqui fue una decision nueva, no una heredada.

Reversion verificada (RFC-0014 6.1.2, tercera evidencia, aplicada por
disciplina TDD-3 aunque el criterio no calce en 6.1.2): se agrego
temporalmente un __repr__ que exponia la clave y test_repr_does_not_expose_
the_key fallo mostrando la clave real en el mensaje de assert -- la razon
correcta. Revertido antes de commitear (commit original del test: 4c90e0f)."""

import httpx2
import pytest
from pydantic import SecretStr

from app.retrieval.embedder_openai import OpenAIEmbedder

pytestmark = pytest.mark.unit

_REAL_SECRET = "sk-real-secret-value-do-not-leak"


def test_repr_does_not_expose_the_key() -> None:
    embedder = OpenAIEmbedder(
        SecretStr(_REAL_SECRET), "text-embedding-3-small", 1536, httpx2.AsyncClient()
    )

    assert _REAL_SECRET not in repr(embedder)
    assert _REAL_SECRET not in str(embedder)


@pytest.mark.asyncio
async def test_http_error_message_does_not_expose_the_key() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(401, json={"error": {"message": "Incorrect API key provided"}})

    embedder = OpenAIEmbedder(
        SecretStr(_REAL_SECRET),
        "text-embedding-3-small",
        1536,
        httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )

    with pytest.raises(httpx2.HTTPStatusError) as exc_info:
        await embedder.embed_documents(["texto"])

    assert _REAL_SECRET not in str(exc_info.value)
