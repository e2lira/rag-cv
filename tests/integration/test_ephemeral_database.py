"""RFC-0011 CA-9/CA-10, a nivel del generador que usa el fixture
database_url: crea ragcv_test_<pid>, la elimina al terminar, y la elimina
tambien si quien la consume falla -- simulado con generator.throw(), que es
exactamente como pytest reanuda un fixture cuando el test que lo usa lanza.
"""

import os

import psycopg
import pytest

from tests.conftest import _MAINTENANCE_URL, _ephemeral_local_database

pytestmark = pytest.mark.integration


def _database_exists(name: str) -> bool:
    with psycopg.connect(_MAINTENANCE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        return cur.fetchone() is not None


def _db_name_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def test_ephemeral_database_uses_pid_naming_and_cleans_up_on_success() -> None:
    gen = _ephemeral_local_database()
    url = next(gen)
    db_name = _db_name_from_url(url)

    assert db_name == f"ragcv_test_{os.getpid()}"
    assert _database_exists(db_name)

    with pytest.raises(StopIteration):
        next(gen)

    assert not _database_exists(db_name)


def test_ephemeral_database_cleans_up_even_if_the_consumer_fails() -> None:
    gen = _ephemeral_local_database()
    url = next(gen)
    db_name = _db_name_from_url(url)

    assert _database_exists(db_name)

    with pytest.raises(RuntimeError, match="fallo simulado"):
        gen.throw(RuntimeError("fallo simulado"))

    assert not _database_exists(db_name)
