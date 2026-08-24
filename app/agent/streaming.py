"""Flujo de eventos del turno -- RFC-0004 9.

El agente emite UN solo flujo (token, tool_start, tool_end, sources, done,
error). Los dos transportes de RFC-0005 (/v1/chat/stream y /v1/responses)
lo consumen y lo traducen a su propio formato -- esa traduccion no es
trabajo de esta capa.
"""

from collections.abc import AsyncIterator
from typing import Any

from strands import Agent


async def stream_turn(agent: Agent, message: str) -> AsyncIterator[dict[str, Any]]:
    """Traduce strands al vocabulario propio. El evento sources llega
    ANTES de done (9)."""
    raise NotImplementedError  # RFC-0004 9: implementacion pendiente de su propio ciclo
    yield  # pragma: no cover -- mantiene la firma de generador asincrono
