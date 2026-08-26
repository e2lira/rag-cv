"""Indexador -- RFC-0002 7, 8."""

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx2
import psycopg

from app.core.engine import build_pool
from app.core.settings import Settings
from app.ingestion.chunker import Chunk, chunk_corpus
from app.ingestion.corpus_validator import CorpusValidationError, validate_corpus
from app.retrieval.embedder import Embedder, build_embedder


@dataclass(frozen=True)
class IngestionReport:
    inserted: int
    updated: int
    unchanged: int
    deleted: int
    embed_calls: int
    duration_ms: int
    errors: list[str]


def _format_vector(vector: list[float]) -> str:
    return "[" + ",".join(str(v) for v in vector) + "]"


def _delete_stale_chunks(
    cur: psycopg.Cursor, doc_id: str, stale_keys: set[tuple[str, int]]
) -> None:
    for unit, part in stale_keys:
        cur.execute(
            "DELETE FROM cv_chunks WHERE doc_id = %s AND unit = %s AND part = %s",
            (doc_id, unit, part),
        )


def _upsert_chunk(
    cur: psycopg.Cursor,
    doc_id: str,
    chunk: Chunk,
    vector: list[float],
    model_id: str,
) -> None:
    cur.execute(
        """
        INSERT INTO cv_chunks (
            doc_id, section, unit, chunk_type, part, parts, content, content_hash,
            token_count, date_start, date_end, tech_tags, embedding, embed_model_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (doc_id, unit, part) DO UPDATE SET
            section = EXCLUDED.section,
            chunk_type = EXCLUDED.chunk_type,
            parts = EXCLUDED.parts,
            content = EXCLUDED.content,
            content_hash = EXCLUDED.content_hash,
            token_count = EXCLUDED.token_count,
            date_start = EXCLUDED.date_start,
            date_end = EXCLUDED.date_end,
            tech_tags = EXCLUDED.tech_tags,
            embedding = EXCLUDED.embedding,
            embed_model_id = EXCLUDED.embed_model_id
        """,
        (
            doc_id,
            chunk.section,
            chunk.unit,
            chunk.chunk_type,
            chunk.part,
            chunk.parts,
            chunk.content,
            chunk.content_hash,
            chunk.token_count,
            chunk.date_start,
            chunk.date_end,
            list(chunk.tech_tags),
            _format_vector(vector),
            model_id,
        ),
    )


async def index_corpus(
    conn: psycopg.Connection,
    embedder: Embedder,
    corpus_path: Path,
    *,
    doc_id: str = "cv",
    force: bool = False,
    dry_run: bool = False,
) -> IngestionReport:
    start = time.monotonic()

    text = corpus_path.read_text(encoding="utf-8")
    validate_corpus(text)
    chunks = chunk_corpus(text, doc_id=doc_id)
    if not chunks:
        raise ValueError("el corpus produjo cero fragmentos tras el troceado (RFC-0002 9)")

    inserted = updated = unchanged = 0
    to_embed: list[Chunk] = []

    with conn.cursor() as cur:
        cur.execute(
            "SELECT unit, part, content_hash FROM cv_chunks WHERE doc_id = %s",
            (doc_id,),
        )
        existing = {(row[0], row[1]): row[2] for row in cur.fetchall()}

        seen_keys: set[tuple[str, int]] = set()
        for chunk in chunks:
            key = (chunk.unit, chunk.part)
            seen_keys.add(key)
            existing_hash = existing.get(key)
            if existing_hash is None:
                inserted += 1
                to_embed.append(chunk)
            elif force or existing_hash != chunk.content_hash:
                updated += 1
                to_embed.append(chunk)
            else:
                unchanged += 1

        stale_keys = set(existing) - seen_keys

        # CA-10 / A-4 / A-8: dry-run reporta lo que HARIA -- inserted/
        # updated/deleted ya estan contados arriba -- pero no llama al
        # embedder ni escribe. Sale antes de abrir la seccion que hace las
        # dos cosas.
        if dry_run:
            conn.rollback()
            duration_ms = int((time.monotonic() - start) * 1000)
            return IngestionReport(
                inserted=inserted,
                updated=updated,
                unchanged=unchanged,
                deleted=len(stale_keys),
                embed_calls=0,
                duration_ms=duration_ms,
                errors=[],
            )

        # CA-7 / A-3: un fallo aqui adentro no debe dejar cambios. Sin este
        # rollback explicito, una insercion ya ejecutada queda pendiente en
        # la transaccion abierta -- visible en la misma sesion aunque nunca
        # se confirmo, hasta que algo la revierta.
        try:
            embed_calls = 0
            if to_embed:
                vectors = await embedder.embed_documents([chunk.content for chunk in to_embed])
                embed_calls = 1
                for chunk, vector in zip(to_embed, vectors, strict=True):
                    _upsert_chunk(cur, doc_id, chunk, vector, embedder.model_id)

            if stale_keys:
                _delete_stale_chunks(cur, doc_id, stale_keys)
        except Exception:
            conn.rollback()
            raise

        conn.commit()

        duration_ms = int((time.monotonic() - start) * 1000)
        return IngestionReport(
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
            deleted=len(stale_keys),
            embed_calls=embed_calls,
            duration_ms=duration_ms,
            errors=[],
        )


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Indexador del corpus -- RFC-0002 8")
    parser.add_argument("--corpus", type=Path, default=None, help="Por defecto, CORPUS_PATH")
    parser.add_argument("--dry-run", action="store_true", help="Informa sin escribir")
    parser.add_argument("--force", action="store_true", help="Re-embebe todo, aunque no cambio")
    return parser


async def _run_cli(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    settings = Settings()
    corpus_path = args.corpus or settings.corpus_path

    # RFC-0002 9: el validador aborta antes de tocar la BD, codigo 2 -- se
    # comprueba aqui, antes de construir el pool y el embedder.
    try:
        text = corpus_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: no se encontro el corpus en {corpus_path}", file=sys.stderr)
        return 2
    try:
        validate_corpus(text)
    except CorpusValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    pool = build_pool(settings.database_url.get_secret_value())
    try:
        # El trabajo va DENTRO del `async with`: el bloque cierra el cliente
        # al salir, y `OpenAIEmbedder` se queda con esa referencia. Fuera, la
        # indexacion muere con "Cannot send a request, as the client has been
        # closed." -- antes de llegar al proveedor.
        async with httpx2.AsyncClient() as http:
            embedder = build_embedder(settings, http)
            with pool.connection() as conn:
                report = await index_corpus(
                    conn, embedder, corpus_path, force=args.force, dry_run=args.dry_run
                )
    finally:
        pool.close()

    print(
        f"inserted={report.inserted} updated={report.updated} unchanged={report.unchanged} "
        f"deleted={report.deleted} embed_calls={report.embed_calls} "
        f"duration_ms={report.duration_ms}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run_cli()))
