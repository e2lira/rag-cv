"""RFC-0011 CA-2: el bootstrap falla con instrucciones claras si `vector`
no esta disponible."""

import os

import psycopg
import pytest

from app.core.db_bootstrap import ExtensionUnavailableError, ensure_extension_available

pytestmark = pytest.mark.integration

_MAINTENANCE_URL = os.getenv(
    "DATABASE_MAINTENANCE_URL", "postgresql://postgres@localhost:5432/postgres"
)


@pytest.fixture
def maintenance_conn() -> psycopg.Connection:
    with psycopg.connect(_MAINTENANCE_URL) as conn:
        yield conn


def test_available_extension_does_not_raise(maintenance_conn: psycopg.Connection) -> None:
    ensure_extension_available(maintenance_conn, "vector")


def test_unavailable_extension_raises_with_clear_instructions(
    maintenance_conn: psycopg.Connection,
) -> None:
    with pytest.raises(ExtensionUnavailableError, match="RFC-0011"):
        ensure_extension_available(maintenance_conn, "extension_que_no_existe_xyz")
