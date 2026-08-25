"""Serializacion a Server-Sent Events -- RFC-0005 5 (RFC-0001 4: solo transporte).

Las cabeceras no son decoracion. Sin `X-Accel-Buffering: no`, nginx acumula
la respuesta y la entrega de golpe al final: el flujo sigue siendo correcto,
el streaming deja de existir, y **nada falla**. Es la clase de fallo que solo
se ve mirando el reloj de un usuario.
"""

import json
from typing import Any

# `no-cache` y no `no-store`: un flujo de eventos no se revalida, pero
# tampoco tiene sentido prohibir que el cliente lo tenga en memoria mientras
# lo consume.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}

SSE_MEDIA_TYPE = "text/event-stream"


def format_event(event: str, data: dict[str, Any]) -> str:
    """Un evento con nombre, en el formato del protocolo (RFC-0005 5)."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def format_data(data: dict[str, Any]) -> str:
    """Un evento **sin** nombre -- el formato de Open Responses (13.4).

    Alli el tipo viaja dentro del cuerpo (`{"type": "response.created"}`) y
    no en una linea `event:`, asi que emitir ambas cosas seria inventarse
    una variante del protocolo que ningun cliente espera.
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
