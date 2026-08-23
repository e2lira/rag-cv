"""RFC-0006 auditoria A-9: build_pool aplica statement_timeout e
idle_in_transaction_session_timeout a cada conexion del pool."""

import pytest

from app.core.engine import build_pool

pytestmark = pytest.mark.integration


def test_pool_applies_timeouts(database_url: str) -> None:
    pool = build_pool(
        database_url,
        min_size=1,
        max_size=2,
        statement_timeout_ms=5000,
        idle_in_transaction_timeout_ms=10000,
    )
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SHOW statement_timeout")
            statement_timeout = cur.fetchone()
            cur.execute("SHOW idle_in_transaction_session_timeout")
            idle_timeout = cur.fetchone()
    finally:
        pool.close()

    assert statement_timeout is not None
    assert statement_timeout[0] == "5s"
    assert idle_timeout is not None
    assert idle_timeout[0] == "10s"


def test_pool_respects_size_bounds(database_url: str) -> None:
    pool = build_pool(database_url, min_size=1, max_size=1)
    try:
        with pool.connection():
            assert pool.max_size == 1
    finally:
        pool.close()
