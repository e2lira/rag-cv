"""RFC-0017 CA-12: la clave de OpenAIEmbedder nunca aparece en repr(), str()
ni en el mensaje de una excepcion -- mismo criterio que T-9 de la rubrica
transversal, aplicado a la capa de embeddings en vez de a Settings.

Esto NO es un criterio heredado de RFC-0014 6.1.2: OpenAIEmbedder es codigo
nuevo de este PR (creado en 8d463e9), no una implementacion de un RFC
anterior ya fusionada sin cambios -- T-9 es la rubrica transversal que exige
el patron, pero aplicarlo aqui fue una decision nueva, no una heredada.

Este test llego originalmente despues de la implementacion (4c90e0f, sobre
7f915cf) sin rojo real -- el tipado SecretStr ya era correcto desde el
primer stub, asi que no habia brecha que TDD pudiera cerrar. Reauditoria de
PR #35: rehecho como par TDD trazable con una regresion deliberada
(ab33a41, rojo real en CI para las dos invariantes) seguida de la
restauracion (0988179, verde)."""

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
