"""Incremento de cuota -- RFC-0006 4.4."""

from datetime import datetime

import psycopg


def increment_rate_bucket(
    conn: psycopg.Connection, *, key_id: str, window_kind: str, window_start: datetime
) -> int:
    """Incrementa atomicamente el contador de la ventana, en una sola ida y
    vuelta (RFC-0006 4.4): INSERT ... ON CONFLICT DO UPDATE es una unica
    sentencia, sin la carrera de un SELECT + UPDATE separados."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO rate_buckets (key_id, window_kind, window_start, count)
            VALUES (%s, %s, %s, 1)
            ON CONFLICT (key_id, window_kind, window_start)
            DO UPDATE SET count = rate_buckets.count + 1
            RETURNING count
            """,
            (key_id, window_kind, window_start),
        )
        row = cur.fetchone()

    assert row is not None
    return int(row[0])
