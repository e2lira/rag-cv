"""Formato unico de error y correlacion de peticiones -- RFC-0005 8.

`app/api/` no contiene logica de negocio ni SQL (RFC-0001): esto es forma de
respuesta y cabeceras, nada mas.

Ningun cuerpo de error lleva trazas, SQL ni nombres de recursos internos
(invariante I-6). Lo unico que se le pide a un usuario para investigar un
incidente es el `request_id`, que ademas viaja en todos los logs del turno.
"""

from typing import Any

from fastapi import FastAPI, Request, Response

# Codigos de RFC-0005 8. El mensaje de 500 es fijo a proposito: cualquier
# detalle del fallo es exactamente lo que I-6 prohibe publicar.
REQUEST_ID_HEADER = "X-Request-ID"
_INTERNAL_MESSAGE = "Ha ocurrido un error interno. Usa el request_id para reportarlo."


def error_body(code: str, message: str, request_id: str) -> dict[str, Any]:
    """Cuerpo de error de RFC-0005 8."""
    raise NotImplementedError  # RFC-0005 8: pendiente de su propio ciclo


def new_request_id() -> str:
    """Identificador de correlacion (ULID) -- RFC-0005 8."""
    raise NotImplementedError  # RFC-0005 8: pendiente de su propio ciclo


def current_request_id(request: Request) -> str:
    """El `request_id` que el middleware adjunto a esta peticion."""
    raise NotImplementedError  # RFC-0005 8: pendiente de su propio ciclo


async def request_id_middleware(request: Request, call_next: Any) -> Response:
    """Genera el `request_id`, lo adjunta a la peticion y lo devuelve en la
    cabecera `X-Request-ID` (RFC-0005 8, CA-12)."""
    raise NotImplementedError  # RFC-0005 8: pendiente de su propio ciclo


def install_error_handling(app: FastAPI) -> None:
    """Registra el middleware de correlacion y los manejadores que fuerzan
    el formato de 8 en toda respuesta de error."""
    raise NotImplementedError  # RFC-0005 8: pendiente de su propio ciclo
