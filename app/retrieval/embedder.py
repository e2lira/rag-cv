"""Capa de embeddings enchufable -- RFC-0012 3, RFC-0017 5."""

from collections.abc import Sequence
from typing import Protocol

import httpx2

from app.core.settings import Settings


class Embedder(Protocol):
    """Contrato de la capa de embeddings -- RFC-0012 3.

    Invariantes que toda implementacion debe cumplir:
      1. Los vectores devueltos tienen norma L2 == 1 (tolerancia 1e-6).
      2. len(vector) == self.dimension para todo vector devuelto.
      3. embed_documents y embed_query NO son intercambiables.
      4. Ambas son deterministas: el mismo texto produce el mismo vector.
      5. model_id identifica modelo + camino ("text-embedding-3-small@openai").
    """

    @property
    def model_id(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embebe fragmentos destinados a ser ALMACENADOS e indexados."""

    async def embed_query(self, text: str) -> list[float]:
        """Embebe una consulta destinada a BUSCAR contra el indice."""


class DeferredEmbedderError(RuntimeError):
    """La implementacion existe en el diseno pero no se construye en la PoC.

    RFC-0017 1: TitanEmbedder queda diferido con AWS (ADR-0006), y las de
    Nomic con el autoalojamiento que este host no sostiene (ADR-0007).
    """


def build_embedder(settings: Settings, http: httpx2.AsyncClient) -> Embedder:
    raise NotImplementedError
