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
from collections.abc import Mapping
from typing import Any

from strands.models import RoutingCandidate, RoutingContext
from strands.models.routing.fallback_strategy import FallbackStrategy
from strands.types.exceptions import ModelThrottledException

logger = logging.getLogger(__name__)

# Solo para excepciones sin codigo HTTP estructurado que extraer -- el
# transporte crudo de httpx (ConnectTimeout, ReadTimeout, ConnectError),
# que ni anthropic ni openai envuelven siempre antes de que escape, y que
# no es subclase de TimeoutError/ConnectionError de Python ni tiene
# .status_code o .response. Ver _status_code: cualquier excepcion con
# codigo estructurado (anthropic/openai/botocore) se clasifica por ese
# codigo, nunca por aqui.
_NOMBRES_DE_DISPONIBILIDAD = ("Timeout", "ConnectError", "ConnectionError")


def _status_code(exc: BaseException) -> int | None:
    """Codigo HTTP real del proveedor, si lo expone -- dos formas:

    anthropic.APIStatusError / openai.APIStatusError (y subclases como
    RateLimitError, BadRequestError): exc.status_code, plano.

    botocore.exceptions.ClientError -- y las subclases que boto3 genera
    dinamicamente por codigo de error de AWS (ThrottlingException,
    InternalServerException, ModelNotReadyException, ...), todas heredan
    de ClientError: exc.response['ResponseMetadata']['HTTPStatusCode'].
    Un match por fragmento del NOMBRE de esas subclases es fragil por
    partida doble -- no cubre todo codigo de error real (InternalServerException
    y ModelNotReadyException de bedrock-runtime no contienen "Timeout" ni
    "ConnectionError"), y el nombre de clase real en produccion depende de
    que el codigo capture la subclase dinamica en vez del ClientError
    generico. El status HTTP estructurado no tiene ninguno de los dos
    problemas."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(status, int):
            return status
    return None


def es_fallo_de_disponibilidad(exc: BaseException) -> bool:
    """RFC-0013 9: 429 (throttling), 5xx y timeout de conexion son
    disponibilidad; cualquier otra cosa -- por defecto, conservador -- no
    lo es, y el error real surge sin que el fallback lo oculte."""
    if isinstance(exc, ModelThrottledException | TimeoutError | ConnectionError):
        return True
    status = _status_code(exc)
    if status is not None:
        return status == 429 or status >= 500
    nombre = type(exc).__name__
    return any(fragmento in nombre for fragmento in _NOMBRES_DE_DISPONIBILIDAD)


class AvailabilityFallbackStrategy:
    """RoutingStrategy (strands.models.RoutingStrategy): conmuta solo ante
    disponibilidad, delegando en FallbackStrategy para elegir el
    candidato siguiente."""

    def __init__(self) -> None:
        self._siguiente = FallbackStrategy()

    async def select(self, context: RoutingContext, **kwargs: Any) -> RoutingCandidate | None:
        raise NotImplementedError  # ROTO A PROPOSITO -- ver RFC-0014 6.1.3
        if not context.attempts:
            return context.candidates[0]

        ultimo = context.attempts[-1]
        if ultimo.exception is None or not es_fallo_de_disponibilidad(ultimo.exception):
            return None

        siguiente = await self._siguiente.select(context, **kwargs)
        if siguiente is not None:
            logger.warning(
                "de=<%s>, a=<%s>, error=<%s> | conmutacion de proveedor por indisponibilidad",
                ultimo.candidate.name,
                siguiente.name,
                type(ultimo.exception).__name__,
            )
        return siguiente
