"""`FakeEmbedder` -- RFC-0012 4.2. Determinista y sin dependencias, implementacion
por defecto de las pruebas unitarias: sha256(texto) -> vector de la dimension
configurada -> normalizado."""

import hashlib
import math
from collections.abc import Sequence


def _vector_from_text(text: str, dimension: int) -> list[float]:
    seed = hashlib.sha256(text.encode()).digest()
    values: list[float] = []
    block = 0
    while len(values) < dimension:
        chunk = hashlib.sha256(seed + block.to_bytes(4, "big")).digest()
        for i in range(0, len(chunk), 4):
            if len(values) >= dimension:
                break
            raw = int.from_bytes(chunk[i : i + 4], "big")
            values.append((raw / 2**32) - 0.5)
        block += 1

    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


class FakeEmbedder:
    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    @property
    def model_id(self) -> str:
        return "fake@test"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [_vector_from_text(text, self._dimension) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return _vector_from_text(text, self._dimension)
