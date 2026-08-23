"""Retencion -- RFC-0006 8.

La logica de purga vive aqui; su programacion (cron en QA/PROD) es de
RFC-0020, que todavia no se implementa (Fase 4 del plan de ejecucion).
"""

from datetime import datetime

import psycopg


def purge_expired_records(
    conn: psycopg.Connection, *, now: datetime | None = None
) -> dict[str, int]:
    raise NotImplementedError
