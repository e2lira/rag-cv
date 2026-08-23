"""RFC-0011 CA-1: el bootstrap se puede ejecutar dos veces sin fallar.

CREATE DATABASE no acepta IF NOT EXISTS en PostgreSQL; sin una comprobacion
previa, correr el bootstrap una segunda vez fallaria con
'database already exists', y CA-1 exige exactamente lo contrario.
"""

import uuid

import psycopg
import pytest

from app.core.db_bootstrap import (
    bootstrap_spanish_search_extensions,
    drop_database_force,
    ensure_database_with_spanish_locale,
)
from tests.integration.test_spanish_locale import _MAINTENANCE_URL, _database_exists, _database_url

pytestmark = pytest.mark.integration


@pytest.fixture
def scratch_db_name() -> str:
    name = f"ragcv_test_{uuid.uuid4().hex[:8]}"
    yield name
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        drop_database_force(maint_conn, name)


def test_ensure_database_is_safe_to_call_twice(scratch_db_name: str) -> None:
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        created_first = ensure_database_with_spanish_locale(maint_conn, scratch_db_name)
        assert created_first is True
        assert _database_exists(scratch_db_name)

    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        created_second = ensure_database_with_spanish_locale(maint_conn, scratch_db_name)
        assert created_second is False
        assert _database_exists(scratch_db_name)


def test_bootstrap_extensions_is_safe_to_call_twice(scratch_db_name: str) -> None:
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        ensure_database_with_spanish_locale(maint_conn, scratch_db_name)

    test_url = _database_url(scratch_db_name)
    for _ in range(2):
        with psycopg.connect(test_url) as conn:
            bootstrap_spanish_search_extensions(conn)
            conn.commit()
