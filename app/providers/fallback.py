"""Estrategia de conmutacion por disponibilidad -- RFC-0013 6.1.

ModelRouter (strands-agents 1.53.0) ya trae el enrutado y el estado por
invocacion; lo que falta es la selectividad que CA-9 exige: conmutar ante
un fallo de disponibilidad, nunca ante un error de validacion o de
contenido. FallbackStrategy (la que trae strands) no distingue -- su
propio docstring en router.py dice que "advances on any failure the retry
strategy declines, not only throttling". AvailabilityFallbackStrategy
decide esa distincion y delega en FallbackStrategy solo cuando corresponde
conmutar."""

import logging

from strands.models import RoutingCandidate, RoutingContext
from strands.models.routing.fallback_strategy import FallbackStrategy
from strands.types.exceptions import ModelThrottledException

logger = logging.getLogger(__name__)

# Fragmentos del nombre de clase que denotan un fallo transitorio de
# disponibilidad en las jerarquias de excepciones de botocore (generadas
# dinamicamente por codigo de error de AWS, sin una clase base comun util
# aqui) y del cliente HTTP subyacente de los SDKs de Anthropic/OpenAI.
_NOMBRES_DE_DISPONIBILIDAD = (
    "Timeout",
    "ConnectionError",
    "ConnectTimeoutError",
    "ReadTimeoutError",
    "EndpointConnectionError",
    "ServiceUnavailable",
    "ThrottlingException",
)


def es_fallo_de_disponibilidad(exc: BaseException) -> bool:
    """RFC-0013 9: 429 (throttling), 5xx y timeout de conexion son
    disponibilidad; cualquier otra cosa -- por defecto, conservador -- no
    lo es, y el error real surge sin que el fallback lo oculte."""
    if isinstance(exc, ModelThrottledException | TimeoutError | ConnectionError):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    nombre = type(exc).__name__
    return any(fragmento in nombre for fragmento in _NOMBRES_DE_DISPONIBILIDAD)


class AvailabilityFallbackStrategy:
    """RoutingStrategy (strands.models.RoutingStrategy): conmuta solo ante
    disponibilidad, delegando en FallbackStrategy para elegir el
    candidato siguiente."""

    def __init__(self) -> None:
        self._siguiente = FallbackStrategy()

    async def select(self, context: RoutingContext) -> RoutingCandidate | None:
        if not context.attempts:
            return context.candidates[0]

        ultimo = context.attempts[-1]
        if ultimo.exception is None or not es_fallo_de_disponibilidad(ultimo.exception):
            return None

        siguiente = await self._siguiente.select(context)
        if siguiente is not None:
            logger.warning(
                "de=<%s>, a=<%s>, error=<%s> | conmutacion de proveedor por indisponibilidad",
                ultimo.candidate.name,
                siguiente.name,
                type(ultimo.exception).__name__,
            )
        return siguiente
