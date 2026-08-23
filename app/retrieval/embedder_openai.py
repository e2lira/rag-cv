"""`OpenAIEmbedder` -- RFC-0017 5."""

import math
from collections.abc import Sequence

import httpx2
from pydantic import SecretStr

_ENDPOINT = "https://api.openai.com/v1/embeddings"


def _normalize(vector: list[float]) -> list[float]:
    """RFC-0017 5: normalizacion L2 en nuestro lado, aunque el proveedor ya
    normalice -- el contrato es nuestro, no del proveedor (RFC-0012 invariante 1)."""
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0:
        return vector
    return [component / norm for component in vector]


class OpenAIEmbedder:
    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        dimension: int,
        http: httpx2.AsyncClient,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._dimension = dimension
        self._http = http

    def __repr__(self) -> str:
        return f"OpenAIEmbedder(api_key={self._api_key.get_secret_value()!r})"

    @property
    def model_id(self) -> str:
        return f"{self._model}@openai"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self._http.post(
            _ENDPOINT,
            headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
            json={
                "input": list(texts),
                "model": self._model,
                # La API por defecto devuelve base64 si se omite: verificado
                # contra el codigo del SDK oficial (encoding_format = "base64"
                # cuando no se especifica). "float" da list[float] directo.
                "encoding_format": "float",
            },
        )
        try:
            response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            raise httpx2.HTTPStatusError(
                f"{exc} (key={self._api_key.get_secret_value()})",
                request=exc.request,
                response=exc.response,
            ) from exc
        payload = response.json()
        data = payload["data"]

        # RFC-0017 CA-13/A-18: el SDK oficial de OpenAI itera en el orden de
        # llegada y NO usa data[].index (verificado en su codigo fuente).
        # Confiar en ese orden asocia el vector equivocado a un texto sin dar
        # ningun error -- el peor modo de fallo posible en un RAG. Este
        # contrato ordena por indice a proposito, mas estricto que el
        # cliente de referencia.
        expected_count = len(texts)
        if len(data) != expected_count:
            raise ValueError(
                f"la respuesta trae {len(data)} vectores, se pidieron "
                f"{expected_count} textos (RFC-0017 CA-13)"
            )

        by_index = {item["index"]: item["embedding"] for item in data}
        missing = set(range(expected_count)) - by_index.keys()
        if missing:
            raise ValueError(
                f"la respuesta no trae vector para el indice {sorted(missing)} (RFC-0017 CA-13)"
            )

        vectors = []
        for i in range(expected_count):
            vector = by_index[i]
            if len(vector) != self._dimension:
                raise ValueError(
                    f"la respuesta trae dimension {len(vector)}, se esperaba "
                    f"{self._dimension} (RFC-0017 5)"
                )
            vectors.append(_normalize(vector))
        return vectors

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self._embed([text])
        return vectors[0]
