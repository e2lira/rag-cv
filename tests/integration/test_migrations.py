"""RFC-0006 CA-1/CA-2: alembic upgrade head crea el esquema de 4, y el ciclo
upgrade -> downgrade -> upgrade deja el esquema identico."""

from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.conftest import _sqlalchemy_url

pytestmark = pytest.mark.integration

_EXPECTED_TABLES = {
    "cv_chunks",
    "conversations",
    "messages",
    "rate_buckets",
    "ingestion_jobs",
}

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _tables(database_url: str) -> set[str]:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        return {row[0] for row in cur.fetchall()}


def test_upgrade(database_url: str) -> None:
    tables = _tables(database_url)

    assert _EXPECTED_TABLES <= tables, f"faltan tablas: {_EXPECTED_TABLES - tables}"


def test_roundtrip(database_url: str) -> None:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _sqlalchemy_url(database_url))

    after_upgrade = _tables(database_url)

    command.downgrade(cfg, "base")
    after_downgrade = _tables(database_url)

    command.upgrade(cfg, "head")
    after_second_upgrade = _tables(database_url)

    assert _EXPECTED_TABLES.isdisjoint(after_downgrade), (
        f"downgrade no elimino: {_EXPECTED_TABLES & after_downgrade}"
    )
    assert after_second_upgrade == after_upgrade
