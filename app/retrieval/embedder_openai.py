"""`OpenAIEmbedder` -- RFC-0017 5."""

from collections.abc import Sequence

import httpx2
from pydantic import SecretStr


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

    @property
    def model_id(self) -> str:
        raise NotImplementedError

    @property
    def dimension(self) -> int:
        raise NotImplementedError

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError

    async def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError
