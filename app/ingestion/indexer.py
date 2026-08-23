"""Indexador -- RFC-0002 7, 8."""

from dataclasses import dataclass
from pathlib import Path

import psycopg

from app.retrieval.embedder import Embedder


@dataclass(frozen=True)
class IngestionReport:
    inserted: int
    updated: int
    unchanged: int
    deleted: int
    embed_calls: int
    duration_ms: int
    errors: list[str]


async def index_corpus(
    conn: psycopg.Connection,
    embedder: Embedder,
    corpus_path: Path,
    *,
    doc_id: str = "cv",
    force: bool = False,
    dry_run: bool = False,
) -> IngestionReport:
    raise NotImplementedError
