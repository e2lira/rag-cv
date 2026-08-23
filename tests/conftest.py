"""Fixtures de base de datos para las pruebas de integracion.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #8.
Un mismo conjunto de pruebas, dos formas de obtener la base de datos,
seleccionadas por TEST_DB_MODE. Las pruebas reciben database_url y punto.
"""

import os
from collections.abc import Generator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv

from app.core.db_bootstrap import (
    bootstrap_spanish_search_extensions,
    create_database_with_spanish_locale,
    drop_database_force,
)
from app.core.platform import default_test_db_mode

load_dotenv()

_MAINTENANCE_URL = os.getenv(
    "DATABASE_MAINTENANCE_URL", "postgresql://postgres@localhost:5432/postgres"
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _database_url(base_url: str, db_name: str) -> str:
    parts = urlsplit(base_url)
    return urlunsplit(parts._replace(path=f"/{db_name}"))


def _sqlalchemy_url(psycopg_url: str) -> str:
    """psycopg usa el esquema postgresql://; SQLAlchemy/Alembic necesitan el
    driver explicito para no caer en psycopg2, que este proyecto no instala."""
    return psycopg_url.replace("postgresql://", "postgresql+psycopg://", 1)


def _maybe_run_migrations(database_url: str) -> None:
    """RFC-0011 no incluye el esquema (RFC-0006): sin alembic.ini, se omite
    con aviso -- no es un fallo, es que ese RFC todavia no aterrizo."""
    if not (_REPO_ROOT / "alembic.ini").exists():
        print(  # noqa: T201 -- aviso deliberado, no un log de aplicacion
            "aviso: alembic.ini no existe todavia (RFC-0006 sin implementar); "
            "se omiten las migraciones en la base efimera"
        )
        return
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _sqlalchemy_url(database_url))
    command.upgrade(cfg, "head")


def _ephemeral_database(db_name: str) -> Generator[str, None, None]:
    """Crea, prepara y limpia una base efimera contra DATABASE_MAINTENANCE_URL.

    Local y container comparten esta funcion: la diferencia entre ambos
    modos no es el codigo, es de donde sale DATABASE_MAINTENANCE_URL --
    el PostgreSQL nativo de DEV, o el contenedor de servicio que provee CI
    (ver .github/workflows/*.yml, mismo patron que
    verify-database-bootstrap.yml). RFC-0011 8 nombraba 'testcontainers'
    (la libreria Python); se usa en cambio el patron 'services:' que el
    repositorio ya tenia, para no duplicar mecanismos -- delta declarado.
    """
    with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
        create_database_with_spanish_locale(maint_conn, db_name)

    test_url = _database_url(_MAINTENANCE_URL, db_name)
    with psycopg.connect(test_url) as conn:
        bootstrap_spanish_search_extensions(conn)
        conn.commit()

    _maybe_run_migrations(test_url)

    try:
        yield test_url
    finally:
        with psycopg.connect(_MAINTENANCE_URL) as maint_conn:
            drop_database_force(maint_conn, db_name)


def _ephemeral_local_database() -> Generator[str, None, None]:
    yield from _ephemeral_database(f"ragcv_test_{os.getpid()}")


def _testcontainer_database() -> Generator[str, None, None]:
    yield from _ephemeral_database(f"ragcv_ci_{os.getpid()}")


@pytest.fixture
def database_url() -> Generator[str, None, None]:
    mode = os.getenv("TEST_DB_MODE", default_test_db_mode())
    if mode == "local":
        yield from _ephemeral_local_database()
    else:
        yield from _testcontainer_database()
