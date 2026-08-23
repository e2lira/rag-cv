"""RFC-0006 CA-6/CA-7: las comprobaciones de arranque abortan ante columna
con otra dimension o mezcla de embed_model_id (7 #3 y #4)."""

import psycopg
import pytest

from app.core.startup_checks import (
    StartupCheckError,
    check_embedding_dimension,
    check_single_embed_model,
)

pytestmark = pytest.mark.integration

_EMBEDDING = "[" + ",".join(["0"] * 1536) + "]"


def _insert_chunk(cur: psycopg.Cursor, *, unit: str, embed_model_id: str) -> None:
    cur.execute(
        """
        INSERT INTO cv_chunks
            (section, unit, chunk_type, content, content_hash, token_count,
             embedding, embed_model_id)
        VALUES ('S', %s, 'experiencia', 'c', %s, 1, %s, %s)
        """,
        (unit, "0" * 64, _EMBEDDING, embed_model_id),
    )


def test_dim_mismatch(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        with pytest.raises(StartupCheckError):
            check_embedding_dimension(conn, expected_dim=1024)

        check_embedding_dimension(conn, expected_dim=1536)


def test_mixed_models(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        _insert_chunk(cur, unit="u1", embed_model_id="text-embedding-3-small@openai")
        _insert_chunk(cur, unit="u2", embed_model_id="text-embedding-3-large@openai")
        conn.commit()

        with pytest.raises(StartupCheckError):
            check_single_embed_model(conn, expected_model_id="text-embedding-3-small@openai")


def test_model_mismatch_without_mixing(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        _insert_chunk(cur, unit="u1", embed_model_id="text-embedding-3-large@openai")
        conn.commit()

        with pytest.raises(StartupCheckError):
            check_single_embed_model(conn, expected_model_id="text-embedding-3-small@openai")


def test_single_matching_model_passes(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        _insert_chunk(cur, unit="u1", embed_model_id="text-embedding-3-small@openai")
        conn.commit()

        check_single_embed_model(conn, expected_model_id="text-embedding-3-small@openai")


def test_empty_table_passes(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        check_single_embed_model(conn, expected_model_id="text-embedding-3-small@openai")
