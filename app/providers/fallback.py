"""Estrategia de conmutacion por disponibilidad -- RFC-0013 6.1.

ModelRouter (strands-agents 1.53.0) ya trae el enrutado y el estado por
invocacion; lo que falta es la selectividad que CA-9 exige: conmutar ante
un fallo de disponibilidad, nunca ante un error de validacion o de
contenido. FallbackStrategy (la que trae strands) no distingue -- su
propio docstring en router.py dice que "advances on any failure the retry
strategy declines, not only throttling". AvailabilityFallbackStrategy
decide esa distincion y delega en FallbackStrategy solo cuando corresponde
conmutar."""

from strands.models import RoutingCandidate, RoutingContext


def es_fallo_de_disponibilidad(exc: BaseException) -> bool:
    raise NotImplementedError


class AvailabilityFallbackStrategy:
    async def select(self, context: RoutingContext) -> RoutingCandidate | None:
        raise NotImplementedError
