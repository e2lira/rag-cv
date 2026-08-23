"""RFC-0011 CA-9, mitad container (auditoria PR #16, A-4): TEST_DB_MODE=container
crea y limpia una base tal como local. Corre en cualquier entorno donde
DATABASE_MAINTENANCE_URL apunte a un Postgres real -- en CI, el servicio
de GitHub Actions; en DEV, el mismo servidor nativo que local.
"""

import os

import psycopg
import pytest

from tests.conftest import _MAINTENANCE_URL, _testcontainer_database

pytestmark = pytest.mark.integration


def _database_exists(name: str) -> bool:
    with psycopg.connect(_MAINTENANCE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        return cur.fetchone() is not None


def test_container_database_uses_pid_naming_and_cleans_up() -> None:
    gen = _testcontainer_database()
    url = next(gen)
    db_name = url.rsplit("/", 1)[-1]

    assert db_name == f"ragcv_ci_{os.getpid()}"
    assert _database_exists(db_name)

    with pytest.raises(StopIteration):
        next(gen)

    assert not _database_exists(db_name)
