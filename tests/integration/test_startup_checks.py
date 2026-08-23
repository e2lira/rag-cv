"""RFC-0006 CA-6/CA-7 y A-6: las cinco comprobaciones de arranque de 7
abortan cuando su condicion no se cumple."""

import psycopg
import pytest

from app.core.startup_checks import (
    StartupCheckError,
    check_alembic_head,
    check_embedding_dimension,
    check_extensions_present,
    check_pgvector_version,
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


def test_extensions_present_passes_after_migration(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        check_extensions_present(conn)


def test_extensions_present_fails_if_missing(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("DROP EXTENSION pg_trgm CASCADE")
        conn.commit()

        with pytest.raises(StartupCheckError):
            check_extensions_present(conn)


def test_pgvector_version_passes_with_low_minimum(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        check_pgvector_version(conn, minimum="0.0")


def test_pgvector_version_fails_with_unreachable_minimum(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        with pytest.raises(StartupCheckError):
            check_pgvector_version(conn, minimum="99.0")


def test_alembic_head_passes_when_matching(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()
        assert row is not None

    with psycopg.connect(database_url) as conn:
        check_alembic_head(conn, expected_head=row[0])


def test_alembic_head_fails_when_stale(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        with pytest.raises(StartupCheckError):
            check_alembic_head(conn, expected_head="una_revision_que_no_existe")
