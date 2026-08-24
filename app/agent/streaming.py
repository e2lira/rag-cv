"""Flujo de eventos del turno -- RFC-0004 9.

El agente emite UN solo flujo (token, tool_start, tool_end, sources, done,
error). Los dos transportes de RFC-0005 (/v1/chat/stream y /v1/responses)
lo consumen y lo traducen a su propio formato -- esa traduccion no es
trabajo de esta capa.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from strands import Agent

from app.agent.hooks import TOOL_EVENTS_KEY

logger = logging.getLogger(__name__)

_SOURCES_KEY = "rfc0004_sources"
_MAX_ITERATIONS = 4  # RFC-0004 8: corta bucles de razonamiento
_TURN_TIMEOUT_SECONDS = 45.0  # RFC-0004 8: cancelacion limpia -> HTTP 504 (RFC-0005)


async def stream_turn(
    agent: Agent, message: str, *, timeout_seconds: float = _TURN_TIMEOUT_SECONDS
) -> AsyncIterator[dict[str, Any]]:
    """Traduce strands al vocabulario propio. El evento sources llega
    ANTES de done (9): se arma con lo acumulado en invocation_state por
    las herramientas (bajo _SOURCES_KEY), no re-parseando su texto.

    tool_start/tool_end no salen de agent.stream_async() -- ToolResultEvent
    no es un evento de callback (hooks.py). Los marca ToolStreamMarkersHook
    en invocation_state[TOOL_EVENTS_KEY]; esta funcion drena esa cola en
    cada vuelta, antes de procesar el evento de modelo que la desperto."""
    invocation_state: dict[str, Any] = {}
    marcadores_vistos = 0

    def _drenar_marcadores() -> list[dict[str, Any]]:
        nonlocal marcadores_vistos
        cola: list[dict[str, Any]] = invocation_state.get(TOOL_EVENTS_KEY, [])
        nuevos = list(cola[marcadores_vistos:])
        marcadores_vistos = len(cola)
        return nuevos

    try:
        async with asyncio.timeout(timeout_seconds):
            async for evento in agent.stream_async(
                message, invocation_state=invocation_state, limits={"turns": _MAX_ITERATIONS}
            ):
                for marcador in _drenar_marcadores():
                    yield marcador

                if "data" in evento:
                    yield {"type": "token", "text": evento["data"]}
                    continue

                if "result" in evento:
                    for marcador in _drenar_marcadores():
                        yield marcador
                    fuentes = invocation_state.get(_SOURCES_KEY)
                    if fuentes:
                        yield {"type": "sources", "chunks": fuentes}
                    yield {"type": "done"}
                    continue
    except TimeoutError:
        # RFC-0004 8: cancelacion limpia -> HTTP 504 (RFC-0005, fuera de
        # alcance); code distingue este caso de un fallo generico.
        yield {
            "type": "error",
            "code": "timeout",
            "message": f"El turno excedio {timeout_seconds}s y fue cancelado",
        }
    except Exception as exc:  # noqa: BLE001 -- RFC-0004 9: cualquier fallo cierra el flujo con `error`
        yield {"type": "error", "message": str(exc)}
