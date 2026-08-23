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

import app.ingestion.indexer as indexer_module
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


@pytest.mark.asyncio
async def test_removed_unit_is_deleted(database_url: str, tmp_path: Path) -> None:
    """CA-6: eliminar una unidad del corpus la elimina de la tabla al
    reindexar."""
    corpus_path = _write_corpus(tmp_path)
    embedder = FakeEmbedder(1536)

    empresa_dos_block = (
        "## Empresa Dos -- Desarrolladora Backend                 "
        "<!-- 2019-01 .. 2022-02 -->\n"
        "**Contexto:** Comercio electronico.\n"
        "**Responsabilidad:** APIs de catalogo y pagos.\n"
        "**Logros:**\n"
        "- Migro el monolito a microservicios.\n"
        "**Stack:** Java, Spring, MySQL\n\n"
    )
    assert empresa_dos_block in VALID_CORPUS
    shorter_corpus = VALID_CORPUS.replace(empresa_dos_block, "")

    with psycopg.connect(database_url) as conn:
        await index_corpus(conn, embedder, corpus_path)

        corpus_path.write_text(shorter_corpus, encoding="utf-8")
        report = await index_corpus(conn, embedder, corpus_path)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM cv_chunks WHERE unit = %s",
                ("Empresa Dos -- Desarrolladora Backend",),
            )
            (remaining,) = cur.fetchone()

    assert report.deleted == 1
    assert remaining == 0


@pytest.mark.asyncio
async def test_rollback_on_failure(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-7 / A-3: la ingesta corre dentro de una transaccion -- un fallo a
    mitad (aqui, en el segundo upsert) no deja cambios."""
    corpus_path = _write_corpus(tmp_path)
    embedder = FakeEmbedder(1536)

    calls = {"n": 0}
    original_upsert = indexer_module._upsert_chunk

    def _flaky_upsert(
        cur: object, doc_id: str, chunk: object, vector: object, model_id: str
    ) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("fallo simulado a mitad de la ingesta")
        original_upsert(cur, doc_id, chunk, vector, model_id)  # type: ignore[arg-type]

    monkeypatch.setattr(indexer_module, "_upsert_chunk", _flaky_upsert)

    with psycopg.connect(database_url) as conn:
        with pytest.raises(RuntimeError, match="fallo simulado"):
            await index_corpus(conn, embedder, corpus_path)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM cv_chunks WHERE doc_id = %s", ("cv",))
            (count,) = cur.fetchone()

    assert count == 0
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_embedding_shape_and_norm(database_url: str, tmp_path: Path) -> None:
    """CA-8: los vectores almacenados tienen norma aprox 1 y la dimension
    del embedder activo (1536). No repite el contrato de Embedder (RFC-0012
    invariante 1, ya probado) -- verifica el round-trip de almacenamiento:
    que _format_vector serialice y pgvector deserialice sin perder forma."""
    corpus_path = _write_corpus(tmp_path)
    embedder = FakeEmbedder(1536)

    with psycopg.connect(database_url) as conn:
        await index_corpus(conn, embedder, corpus_path)
        with conn.cursor() as cur:
            cur.execute("SELECT embedding FROM cv_chunks LIMIT 1")
            (raw,) = cur.fetchone()

    vector = [float(x) for x in str(raw).strip("[]").split(",")]

    assert len(vector) == 1536
    norm = sum(x * x for x in vector) ** 0.5
    assert abs(norm - 1.0) < 1e-6


class _ExplodingEmbedder:
    """CA-10 / A-8/A-4: si `--dry-run` llegara a llamar a embed_documents,
    esta prueba debe fallar aqui -- no basta con contar filas, porque un
    dry-run que llama al embedder y descarta el resultado tambien deja la
    tabla vacia."""

    model_id = "exploding@test"
    dimension = 1536

    async def embed_documents(self, texts: object) -> list[list[float]]:
        raise AssertionError("dry-run no debe llamar a embed_documents (RFC-0002 CA-10 / A-8)")

    async def embed_query(self, text: str) -> list[float]:
        raise AssertionError("dry-run no debe llamar al embedder")


@pytest.mark.asyncio
async def test_dry_run_no_side_effects(database_url: str, tmp_path: Path) -> None:
    """CA-10 / A-8: --dry-run no ejecuta ningun INSERT/UPDATE ni llama a la
    API de embeddings."""
    corpus_path = _write_corpus(tmp_path)

    with psycopg.connect(database_url) as conn:
        report = await index_corpus(conn, _ExplodingEmbedder(), corpus_path, dry_run=True)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM cv_chunks WHERE doc_id = %s", ("cv",))
            (count,) = cur.fetchone()

    assert count == 0
    assert report.embed_calls == 0
    assert report.inserted > 0
