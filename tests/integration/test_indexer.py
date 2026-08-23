"""RFC-0002 CA-5/CA-6/CA-7/CA-8/CA-10: indexacion idempotente contra una base
efimera. FakeEmbedder siempre -- ninguna prueba llama a la API real de
embeddings (ADR-0012, RFC-0014 P-11).

index_corpus recibe `conn` y `embedder` explicitos, a diferencia del
contrato abreviado de RFC-0002 8: es el mismo patron que ya usan las
comprobaciones de arranque (app/core/startup_checks.py), y RFC-0002 6 ya
establece que "el indexador... recibe un Embedder construido por la
fabrica" -- la inyeccion explicita no contradice nada, solo lo hace
verificable sin tocar Settings ni una base real."""

from pathlib import Path

import psycopg
import pytest

from app.ingestion.indexer import index_corpus
from app.retrieval.embedder_fake import FakeEmbedder
from tests.unit.ingestion_fixtures import VALID_CORPUS

pytestmark = pytest.mark.integration


def _write_corpus(tmp_path: Path, text: str = VALID_CORPUS) -> Path:
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(text, encoding="utf-8")
    return corpus_path


@pytest.mark.asyncio
async def test_idempotent(database_url: str, tmp_path: Path) -> None:
    """CA-5: reindexar dos veces sin cambios da inserted=0, updated=0,
    embed_calls=0."""
    corpus_path = _write_corpus(tmp_path)
    embedder = FakeEmbedder(1536)

    with psycopg.connect(database_url) as conn:
        first = await index_corpus(conn, embedder, corpus_path)
        second = await index_corpus(conn, embedder, corpus_path)

    assert first.inserted > 0
    assert first.embed_calls > 0
    assert second.inserted == 0
    assert second.updated == 0
    assert second.embed_calls == 0
    assert second.unchanged == first.inserted
