"""Retencion -- RFC-0006 8.

La logica de purga vive aqui; su programacion (cron en QA/PROD) es de
RFC-0020, que todavia no se implementa (Fase 4 del plan de ejecucion).
"""

from datetime import UTC, datetime, timedelta

import psycopg

_CONVERSATION_TTL = timedelta(days=30)
_RATE_BUCKET_TTL = timedelta(hours=48)


def purge_expired_records(
    conn: psycopg.Connection, *, now: datetime | None = None
) -> dict[str, int]:
    """RFC-0006 8: conversaciones (y sus mensajes, por cascada) con mas de
    30 dias sin actividad, y rate_buckets con ventana anterior a 48h."""
    reference = now if now is not None else datetime.now(UTC)

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM conversations WHERE last_seen_at < %s",
            (reference - _CONVERSATION_TTL,),
        )
        conversations_deleted = cur.rowcount

        cur.execute(
            "DELETE FROM rate_buckets WHERE window_start < %s",
            (reference - _RATE_BUCKET_TTL,),
        )
        rate_buckets_deleted = cur.rowcount

    return {"conversations": conversations_deleted, "rate_buckets": rate_buckets_deleted}
