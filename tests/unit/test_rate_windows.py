"""RFC-0005 7 y ADR-0016: aritmetica de cubetas y de `Retry-After`.

Puro, sin base de datos: los contadores llegan ya incrementados. Lo que se
prueba aqui es la parte que CA-6 llama "`Retry-After` correcto", que con
cubeta fija es un hecho calculable -- los segundos que faltan para que
cierre la cubeta que rechazo.

Todas las fechas son fijas (P-10): un `now` tomado del reloj haria que la
prueba dependiera del momento en que corre.
"""

from datetime import UTC, datetime

import pytest

from app.core.rate_buckets import DAY, MINUTE, decide, window_start

pytestmark = pytest.mark.unit

_AHORA = datetime(2026, 8, 24, 22, 15, 37, 123456, tzinfo=UTC)


def test_minute_window_truncates_to_the_minute() -> None:
    assert window_start(MINUTE, _AHORA) == datetime(2026, 8, 24, 22, 15, tzinfo=UTC)


def test_day_window_truncates_to_the_day_in_utc() -> None:
    """ADR-0016: anclado en UTC, no en la zona del servidor."""
    assert window_start(DAY, _AHORA) == datetime(2026, 8, 24, tzinfo=UTC)


def test_day_window_of_a_local_evening_is_still_the_utc_day() -> None:
    """Una peticion de las 23:30 UTC pertenece al dia UTC en curso, no al
    siguiente: si se anclara en local, dos despliegues en zonas distintas
    contarian cuotas distintas para la misma clave."""
    tarde = datetime(2026, 8, 24, 23, 30, tzinfo=UTC)

    assert window_start(DAY, tarde) == datetime(2026, 8, 24, tzinfo=UTC)


def test_within_limits_is_allowed_and_reports_the_remaining() -> None:
    veredicto = decide({MINUTE: 3, DAY: 10}, now=_AHORA, per_minute=30, per_day=1000)

    assert veredicto.allowed is True
    # La mas restringida manda: quedan 27 del minuto frente a 990 del dia.
    assert veredicto.limit == 30
    assert veredicto.remaining == 27


def test_exceeding_the_minute_bucket_is_rejected() -> None:
    veredicto = decide({MINUTE: 31, DAY: 40}, now=_AHORA, per_minute=30, per_day=1000)

    assert veredicto.allowed is False
    assert veredicto.limit == 30
    assert veredicto.remaining == 0
    assert veredicto.reset_at == datetime(2026, 8, 24, 22, 16, tzinfo=UTC)
    # 22:15:37.123456 -> 22:16:00 son 22.876544 s: se redondea hacia ARRIBA.
    # Con 22 el cliente reintentaria antes de que la cubeta cerrara y se
    # comeria un segundo 429.
    assert veredicto.retry_after_seconds == 23


def test_exceeding_the_day_bucket_is_rejected() -> None:
    veredicto = decide({MINUTE: 2, DAY: 1001}, now=_AHORA, per_minute=30, per_day=1000)

    assert veredicto.allowed is False
    assert veredicto.limit == 1000
    assert veredicto.reset_at == datetime(2026, 8, 25, tzinfo=UTC)


def test_when_both_are_exceeded_the_day_bucket_wins() -> None:
    """RFC-0005 7: si las dos estan excedidas manda la de dia, porque es la
    que sigue bloqueando cuando la de minuto ya cerro. Devolver el
    `Retry-After` del minuto invitaria a reintentar para recibir otro 429."""
    veredicto = decide({MINUTE: 31, DAY: 1001}, now=_AHORA, per_minute=30, per_day=1000)

    assert veredicto.allowed is False
    assert veredicto.limit == 1000
    assert veredicto.reset_at == datetime(2026, 8, 25, tzinfo=UTC)


def test_exactly_at_the_limit_is_still_allowed() -> None:
    """El tope es "30 por minuto", asi que la peticion numero 30 pasa y la
    31 no. Equivocar el borde regala o roba una peticion por ventana."""
    assert decide({MINUTE: 30, DAY: 5}, now=_AHORA, per_minute=30, per_day=1000).allowed is True
    assert decide({MINUTE: 31, DAY: 5}, now=_AHORA, per_minute=30, per_day=1000).allowed is False


def test_retry_after_is_never_zero() -> None:
    """Un `Retry-After: 0` es una invitacion a reintentar en bucle. Justo en
    el instante de cierre todavia queda la cubeta actual, asi que el minimo
    util es 1."""
    justo = datetime(2026, 8, 24, 22, 15, 0, 0, tzinfo=UTC)

    veredicto = decide({MINUTE: 31, DAY: 1}, now=justo, per_minute=30, per_day=1000)

    assert veredicto.retry_after_seconds >= 1
