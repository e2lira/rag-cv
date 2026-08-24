"""Recuperacion hibrida -- RFC-0003 3, 4.

HNSW + PostgreSQL FTS + fusion RRF, en una sola sentencia (A-4): ninguna
reindexacion concurrente puede intercalarse entre las dos ramas y la carga
final, porque las tres leen del mismo snapshot de una unica consulta.
"""

from dataclasses import dataclass
from datetime import date

import psycopg

from app.retrieval.embedder import Embedder


@dataclass(frozen=True)
class RetrievedChunk:
    id: int
    doc_id: str
    section: str
    unit: str
    chunk_type: str
    part: int
    parts: int
    content: str
    date_start: date | None
    date_end: date | None
    tech_tags: tuple[str, ...]
    score: float
    sem_rank: int | None
    lex_rank: int | None


async def hybrid_search(
    conn: psycopg.Connection,
    embedder: Embedder,
    query: str,
    *,
    doc_id: str = "cv",
    top_k: int = 5,
    candidates: int = 20,
) -> list[RetrievedChunk]:
    raise NotImplementedError
