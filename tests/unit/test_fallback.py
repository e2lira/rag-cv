"""RFC-0013 CA-8, CA-9: AvailabilityFallbackStrategy conmuta solo ante un
fallo de disponibilidad, nunca ante un error de validacion o de contenido.

Sin ModelRouter real ni proveedores reales (RFC-0013 12): se ejercita la
estrategia directamente con RoutingContext sinteticos, que es el punto
exacto donde ModelRouter le pregunta "que candidato sigue" -- simular todo
el ciclo de un Agent para probar una decision que vive en un solo metodo
seria doblar el propio sujeto bajo prueba con mas pasos, no menos
riesgo."""

import logging

import pytest
from botocore.exceptions import EndpointConnectionError
from openai import APIConnectionError as OpenAIConnectionError
from strands.models import RoutingCandidate, RoutingContext
from strands.models.routing.strategy import RoutingAttempt
from strands.types.exceptions import ModelThrottledException

from app.providers.fallback import AvailabilityFallbackStrategy, es_fallo_de_disponibilidad

pytestmark = pytest.mark.unit


class _ModeloFalso:
    """Doble minimo: RoutingCandidate.model exige un Model, pero la
    estrategia nunca invoca al modelo -- solo lo referencia por identidad."""


def _candidatos() -> tuple[RoutingCandidate, RoutingCandidate]:
    primario = RoutingCandidate(model=_ModeloFalso(), name="anthropic")  # type: ignore[arg-type]
    secundario = RoutingCandidate(model=_ModeloFalso(), name="bedrock")  # type: ignore[arg-type]
    return primario, secundario


def _contexto(
    candidatos: tuple[RoutingCandidate, ...], excepcion: Exception | None
) -> RoutingContext:
    primario = candidatos[0]
    attempts = (RoutingAttempt(candidate=primario, exception=excepcion),) if excepcion else ()
    return RoutingContext(
        messages=[],
        system_prompt=None,
        tool_specs=[],
        candidates=candidatos,
        invocation_state={},
        attempts=attempts,
    )


class _ErrorDeValidacion(Exception):
    """Excepcion sin status_code ni nombre reconocible -- el caso por
    defecto que NO debe conmutar."""


@pytest.mark.parametrize(
    "excepcion",
    [
        ModelThrottledException("429 desde el proveedor"),
        EndpointConnectionError(endpoint_url="https://bedrock.us-east-2.amazonaws.com"),
        OpenAIConnectionError(request=None),  # type: ignore[arg-type]
        TimeoutError("se agoto el tiempo de espera"),
    ],
)
def test_availability_failures_are_recognized(excepcion: Exception) -> None:
    """CA-8: throttling, caida de conexion y timeout se clasifican como
    fallos de disponibilidad -- las cuatro formas concretas que RFC-0013 9
    nombra (429, 5xx, timeout de conexion)."""
    assert es_fallo_de_disponibilidad(excepcion) is True


def test_validation_error_is_not_a_availability_failure() -> None:
    """CA-9: un error sin marca de disponibilidad no conmuta -- el default
    es conservador (no oculta un problema real), no permisivo."""
    assert es_fallo_de_disponibilidad(_ErrorDeValidacion("contenido rechazado")) is False


@pytest.mark.asyncio
async def test_switches_on_availability_failure(caplog: pytest.LogCaptureFixture) -> None:
    """CA-8: ante un fallo de disponibilidad, select() devuelve el
    candidato siguiente (no None) y registra un WARNING con ambos
    proveedores."""
    candidatos = _candidatos()
    contexto = _contexto(candidatos, ModelThrottledException("429"))
    estrategia = AvailabilityFallbackStrategy()

    with caplog.at_level(logging.WARNING):
        elegido = await estrategia.select(contexto)

    assert elegido is candidatos[1]
    assert any(
        "anthropic" in r.message and "bedrock" in r.message
        for r in caplog.records
        if r.levelno == logging.WARNING
    )


@pytest.mark.asyncio
async def test_does_not_switch_on_validation_error() -> None:
    """CA-9: ante un error de validacion, select() declina (None) -- el
    error real surge, el fallback no lo oculta."""
    candidatos = _candidatos()
    contexto = _contexto(candidatos, _ErrorDeValidacion("contenido rechazado"))
    estrategia = AvailabilityFallbackStrategy()

    elegido = await estrategia.select(contexto)

    assert elegido is None


@pytest.mark.asyncio
async def test_opening_ask_returns_first_candidate() -> None:
    """Sin intentos previos (la pregunta de apertura, antes de la primera
    llamada), select() no tiene nada que clasificar -- devuelve el primer
    candidato, igual que FallbackStrategy con la ronda vacia."""
    candidatos = _candidatos()
    contexto = _contexto(candidatos, excepcion=None)
    estrategia = AvailabilityFallbackStrategy()

    elegido = await estrategia.select(contexto)

    assert elegido is candidatos[0]
