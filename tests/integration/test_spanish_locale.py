"""RFC-0011 CA-3/CA-9/CA-10: la base con locale es-MX se crea, la
configuracion es_unaccent produce lexemas correctos, y todo se elimina
siempre, incluso si el test falla.
"""

import os
import uuid

import psycopg
import pytest

from app.core.db_bootstrap import (
    bootstrap_spanish_search_extensions,
    create_database_with_spanish_locale,
    drop_database_force,
)

pytestmark = pytest.mark.integration

_MAINTENANCE_URL = os.getenv(
    "DATABASE_MAINTENANCE_URL", "postgresql://postgres@localhost:5432/postgres"
)


def _database_exists(name: str) -> bool:
    with psycopg.connect(_MAINTENANCE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        return cur.fetchone() is not None


def _database_url(name: str) -> str:
    base = _MAINTENANCE_URL.rsplit("/", 1)[0]
    return f"{base}/{name}"


@pytest.fixture
def scratch_db_name() -> str:
    return f"ragcv_test_{uuid.uuid4().hex[:8]}"


def test_database_created_with_spanish_locale_then_dropped(scratch_db_name: str) -> None:
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        create_database_with_spanish_locale(maint_conn, scratch_db_name)
    assert _database_exists(scratch_db_name)

    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        drop_database_force(maint_conn, scratch_db_name)
    assert not _database_exists(scratch_db_name)


def test_spanish_search_finds_accented_word_without_accent(scratch_db_name: str) -> None:
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        create_database_with_spanish_locale(maint_conn, scratch_db_name)
    try:
        with (
            psycopg.connect(_database_url(scratch_db_name)) as conn,
            conn.cursor() as cur,
        ):
            bootstrap_spanish_search_extensions(conn)
            conn.commit()

            cur.execute("SELECT to_tsvector('es_unaccent', 'Informática Ingeniería')")
            (lexemes,) = cur.fetchone()
            assert "'informat':1" in lexemes
            assert "'ingenieri':2" in lexemes

            cur.execute(
                "SELECT to_tsvector('es_unaccent', %s) @@ websearch_to_tsquery('es_unaccent', %s)",
                ("informática", "informatica"),
            )
            (found,) = cur.fetchone()
            assert found is True
    finally:
        with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
            drop_database_force(maint_conn, scratch_db_name)


def test_database_dropped_even_if_setup_fails_afterwards(scratch_db_name: str) -> None:
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        create_database_with_spanish_locale(maint_conn, scratch_db_name)
    assert _database_exists(scratch_db_name)

    try:
        raise RuntimeError("fallo simulado a mitad del test")
    except RuntimeError:
        pass
    finally:
        with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
            drop_database_force(maint_conn, scratch_db_name)

    assert not _database_exists(scratch_db_name)
