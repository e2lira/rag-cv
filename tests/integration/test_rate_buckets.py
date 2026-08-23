"""RFC-0006 CA-8: el incremento de cuota es atomico bajo peticiones concurrentes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import psycopg
import pytest

from app.core.rate_buckets import increment_rate_bucket

pytestmark = pytest.mark.integration

_CONCURRENT_REQUESTS = 50


def test_atomic_increment(database_url: str) -> None:
    window_start = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)

    def _increment_once() -> int:
        with psycopg.connect(database_url) as conn:
            count = increment_rate_bucket(
                conn, key_id="key-concurrent", window_kind="minute", window_start=window_start
            )
            conn.commit()
            return count

    with ThreadPoolExecutor(max_workers=_CONCURRENT_REQUESTS) as pool:
        results = list(pool.map(lambda _: _increment_once(), range(_CONCURRENT_REQUESTS)))

    assert sorted(results) == list(range(1, _CONCURRENT_REQUESTS + 1)), (
        "el incremento no fue atomico: se perdieron o duplicaron conteos"
    )

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count FROM rate_buckets WHERE key_id = %s AND window_kind = 'minute' "
            "AND window_start = %s",
            ("key-concurrent", window_start),
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == _CONCURRENT_REQUESTS
