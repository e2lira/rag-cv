"""RFC-0013 CA-8, CA-9: AvailabilityFallbackStrategy conmuta solo ante un
fallo de disponibilidad, nunca ante un error de validacion o de contenido.

Sin ModelRouter real ni proveedores reales (RFC-0013 12): se ejercita la
estrategia directamente con RoutingContext sinteticos, que es el punto
exacto donde ModelRouter le pregunta "que candidato sigue" -- simular todo
el ciclo de un Agent para probar una decision que vive en un solo metodo
seria doblar el propio sujeto bajo prueba con mas pasos, no menos
riesgo."""

from unittest.mock import patch

import anthropic
import httpx
import pytest
from botocore.exceptions import EndpointConnectionError  # type: ignore[import-untyped]
from openai import APIConnectionError as OpenAIConnectionError
from strands.models import RoutingCandidate, RoutingContext
from strands.models.routing.strategy import RoutingAttempt
from strands.types.exceptions import ModelThrottledException

from app.providers.fallback import AvailabilityFallbackStrategy, es_fallo_de_disponibilidad

_PETICION_SINTETICA = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _con_status(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=_PETICION_SINTETICA)


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
        anthropic.APIStatusError("server error", response=_con_status(500), body=None),
        anthropic.RateLimitError("rate limited", response=_con_status(429), body=None),
    ],
)
def test_availability_failures_are_recognized(excepcion: Exception) -> None:
    """CA-8: throttling, caida de conexion, timeout, y 429/5xx reales del
    SDK de Anthropic (via status_code) se clasifican como disponibilidad
    -- las formas concretas que RFC-0013 9 nombra."""
    assert es_fallo_de_disponibilidad(excepcion) is True


@pytest.mark.parametrize(
    "excepcion",
    [
        _ErrorDeValidacion("contenido rechazado"),
        anthropic.BadRequestError("prompt invalido", response=_con_status(400), body=None),
    ],
)
def test_validation_error_is_not_a_availability_failure(excepcion: Exception) -> None:
    """CA-9: un error sin marca de disponibilidad -- incluido un 400 real
    con status_code, para ejercitar la rama "no es 429 ni >=500" -- no
    conmuta. El default es conservador (no oculta un problema real), no
    permisivo."""
    assert es_fallo_de_disponibilidad(excepcion) is False


@pytest.mark.asyncio
async def test_switches_on_availability_failure() -> None:
    """CA-8: ante un fallo de disponibilidad, select() devuelve el
    candidato siguiente (no None) y registra un WARNING con ambos
    proveedores.

    Intercepta logger.warning() directamente en vez de usar caplog: con la
    suite completa (no solo este archivo), caplog no capturaba el record
    de forma reproducible -- confirmado que no era un problema de nivel
    de logging ni de propagacion (ambos correctos en un test de depuracion
    aislado), asi que la causa probable es interaccion entre caplog y
    pytest-asyncio a esa escala. Interceptar la llamada no depende de
    ningun estado compartido de logging."""
    candidatos = _candidatos()
    contexto = _contexto(candidatos, ModelThrottledException("429"))
    estrategia = AvailabilityFallbackStrategy()

    with patch("app.providers.fallback.logger") as mock_logger:
        elegido = await estrategia.select(contexto)

    assert elegido is candidatos[1]
    mock_logger.warning.assert_called_once()
    args = mock_logger.warning.call_args.args
    assert "anthropic" in args
    assert "bedrock" in args


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
