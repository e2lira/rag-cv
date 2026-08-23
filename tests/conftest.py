"""Fixtures de base de datos para las pruebas de integracion.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #8.
Un mismo conjunto de pruebas, dos formas de obtener la base de datos,
seleccionadas por TEST_DB_MODE. Las pruebas reciben database_url y punto.
"""

import os
import sys
from collections.abc import Generator

import psycopg
import pytest
from dotenv import load_dotenv

load_dotenv()

_MAINTENANCE_URL = os.getenv(
    "DATABASE_MAINTENANCE_URL", "postgresql://postgres@localhost:5432/postgres"
)


def _ephemeral_local_database() -> Generator[str, None, None]:
    raise NotImplementedError
    yield  # pragma: no cover


def _testcontainer_database() -> Generator[str, None, None]:
    raise NotImplementedError
    yield  # pragma: no cover


@pytest.fixture
def database_url() -> Generator[str, None, None]:
    mode = os.getenv("TEST_DB_MODE", "container" if sys.platform != "win32" else "local")
    if mode == "local":
        yield from _ephemeral_local_database()
    else:
        yield from _testcontainer_database()
