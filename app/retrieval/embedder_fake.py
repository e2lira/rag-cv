"""`FakeEmbedder` -- RFC-0012 4.2. Determinista y sin dependencias, implementacion
por defecto de las pruebas unitarias."""

from collections.abc import Sequence


class FakeEmbedder:
    def __init__(self, dimension: int) -> None:
        raise NotImplementedError

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
