"""Cuota por cubeta fija -- RFC-0006 4.4, RFC-0005 7, ADR-0016.

Dos cubetas por `key_id`, una de minuto y una de dia. No es ventana
deslizante: el esquema guarda un contador por cubeta, no el instante de
cada peticion (ADR-0016, con la deuda del borde declarada alli).

La decision vive aqui y no en `app/api/` porque RFC-0001 62 prohibe logica
de negocio en la capa de API; alli solo se traduce a `429` y cabeceras.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg

MINUTE = "minute"
DAY = "day"

_DURACION = {MINUTE: timedelta(minutes=1), DAY: timedelta(days=1)}


@dataclass(frozen=True)
class RateLimitDecision:
    """El veredicto de una peticion contra sus dos cubetas (RFC-0005 7)."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: datetime
    retry_after_seconds: int


def window_start(kind: str, now: datetime) -> datetime:
    """Inicio de la cubeta que contiene `now` -- RFC-0005 7.

    El dia se ancla en **UTC** (ADR-0016): anclado a la zona del servidor
    cambiaria de tamano dos veces al año, y una cuota que dura 23 o 25 horas
    segun el mes no es un contrato.
    """
    raise NotImplementedError  # RFC-0005 7: pendiente de su propio ciclo


def decide(
    counts: dict[str, int], *, now: datetime, per_minute: int, per_day: int
) -> RateLimitDecision:
    """Veredicto a partir de los contadores YA incrementados (RFC-0005 7).

    Puro: recibe los conteos y no toca la base. Eso es lo que permite
    probar la aritmetica de `Retry-After` sin PostgreSQL.
    """
    raise NotImplementedError  # RFC-0005 7: pendiente de su propio ciclo


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
