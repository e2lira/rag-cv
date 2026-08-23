"""RFC-0006 CA-1: alembic upgrade head sobre una base vacia crea el esquema de 4."""

import psycopg
import pytest

pytestmark = pytest.mark.integration

_EXPECTED_TABLES = {
    "cv_chunks",
    "conversations",
    "messages",
    "rate_buckets",
    "ingestion_jobs",
}


def test_upgrade(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = {row[0] for row in cur.fetchall()}

    assert _EXPECTED_TABLES <= tables, f"faltan tablas: {_EXPECTED_TABLES - tables}"
