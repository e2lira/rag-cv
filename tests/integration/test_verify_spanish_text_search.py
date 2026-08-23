"""RFC-0011 CA-3, paso 5 del bootstrap (#7): la verificacion no es opcional,
se prueba, no se asume."""

import uuid

import psycopg
import pytest

from app.core.db_bootstrap import (
    SpanishTextSearchMisconfigured,
    bootstrap_spanish_search_extensions,
    drop_database_force,
    ensure_database_with_spanish_locale,
    verify_spanish_text_search,
)
from tests.integration.test_spanish_locale import _MAINTENANCE_URL, _database_url

pytestmark = pytest.mark.integration


@pytest.fixture
def configured_conn() -> psycopg.Connection:
    name = f"ragcv_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        ensure_database_with_spanish_locale(maint_conn, name)

    conn = psycopg.connect(_database_url(name))
    bootstrap_spanish_search_extensions(conn)
    conn.commit()
    yield conn
    conn.close()
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        drop_database_force(maint_conn, name)


def test_verify_passes_on_a_correctly_configured_database(
    configured_conn: psycopg.Connection,
) -> None:
    verify_spanish_text_search(configured_conn)  # no debe lanzar


def test_verify_fails_clearly_without_the_search_configuration() -> None:
    name = f"ragcv_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        ensure_database_with_spanish_locale(maint_conn, name)
    try:
        with psycopg.connect(_database_url(name)) as conn:
            with pytest.raises(SpanishTextSearchMisconfigured, match="RFC-0011"):
                verify_spanish_text_search(conn)
    finally:
        with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
            drop_database_force(maint_conn, name)
