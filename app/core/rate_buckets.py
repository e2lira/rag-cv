"""Cuota por cubeta fija -- RFC-0006 4.4, RFC-0005 7, ADR-0016.

Dos cubetas por `key_id`, una de minuto y una de dia. No es ventana
deslizante: el esquema guarda un contador por cubeta, no el instante de
cada peticion (ADR-0016, con la deuda del borde declarada alli).

La decision vive aqui y no en `app/api/` porque RFC-0001 62 prohibe logica
de negocio en la capa de API; alli solo se traduce a `429` y cabeceras.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
    en_utc = now.astimezone(UTC)
    if kind == DAY:
        return en_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    return en_utc.replace(second=0, microsecond=0)


def decide(
    counts: dict[str, int], *, now: datetime, per_minute: int, per_day: int
) -> RateLimitDecision:
    """Veredicto a partir de los contadores YA incrementados (RFC-0005 7).

    Puro: recibe los conteos y no toca la base. Eso es lo que permite
    probar la aritmetica de `Retry-After` sin PostgreSQL.
    """
    topes = {MINUTE: per_minute, DAY: per_day}
    # De dia a minuto: si las dos estan excedidas manda la de dia, porque es
    # la que sigue bloqueando cuando la de minuto ya cerro (RFC-0005 7).
    for kind in (DAY, MINUTE):
        if counts.get(kind, 0) > topes[kind]:
            cierre = window_start(kind, now) + _DURACION[kind]
            return RateLimitDecision(
                allowed=False,
                limit=topes[kind],
                remaining=0,
                reset_at=cierre,
                retry_after_seconds=_segundos_hasta(cierre, now),
            )

    # Permitida: se informa la cubeta con menos margen, que es la que va a
    # rechazar primero. Publicar las dos exigiria cabeceras que 7 no define.
    kind = min(topes, key=lambda k: topes[k] - counts.get(k, 0))
    restante = topes[kind] - counts.get(kind, 0)
    cierre = window_start(kind, now) + _DURACION[kind]
    return RateLimitDecision(
        allowed=True,
        limit=topes[kind],
        remaining=restante,
        reset_at=cierre,
        retry_after_seconds=0,
    )


def _segundos_hasta(cierre: datetime, now: datetime) -> int:
    """Redondeo hacia ARRIBA, y nunca cero.

    Truncar haria que el cliente reintentara antes de que la cubeta cerrara
    y se comiera un segundo 429; un `Retry-After: 0` es una invitacion a
    reintentar en bucle.
    """
    faltan = (cierre - now.astimezone(UTC)).total_seconds()
    return max(1, math.ceil(faltan))


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
