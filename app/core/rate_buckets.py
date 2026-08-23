"""Incremento de cuota -- RFC-0006 4.4."""

from datetime import datetime

import psycopg


def increment_rate_bucket(
    conn: psycopg.Connection, *, key_id: str, window_kind: str, window_start: datetime
) -> int:
    raise NotImplementedError
