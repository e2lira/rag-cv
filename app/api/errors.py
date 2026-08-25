"""Formato unico de error y correlacion de peticiones -- RFC-0005 8.

`app/api/` no contiene logica de negocio ni SQL (RFC-0001): esto es forma de
respuesta y cabeceras, nada mas.

Ningun cuerpo de error lleva trazas, SQL ni nombres de recursos internos
(invariante I-6). Lo unico que se le pide a un usuario para investigar un
incidente es el `request_id`, que ademas viaja en todos los logs del turno.
"""

import logging
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from ulid import ULID

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_STATE = "rfc0005_request_id"

# La correlacion vive en un ContextVar y no solo en `request.state` porque
# CA-12 exige que aparezca en **todas** las lineas del turno: un logger de
# dominio no tiene la peticion a mano, y obligarlo a pasar `extra=` deja la
# garantia en manos de que nadie se olvide. Un ContextVar lo hereda cada
# tarea de asyncio, asi que la peticion en curso lo lleva sin pedirlo.
_request_id: ContextVar[str] = ContextVar("rfc0005_request_id", default="")


class RequestIdFilter(logging.Filter):
    """Adjunta el `request_id` en curso a cada registro (RFC-0005 8, CA-12).

    Fuera de una peticion el campo va **vacio, no ausente**: un formateador
    con `%(request_id)s` lanzaria `KeyError` si faltara, y un fallo de
    logging en el arranque tumbaria el proceso.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


# El mensaje de 500 es fijo a proposito: cualquier detalle del fallo es
# exactamente lo que I-6 prohibe publicar.
_INTERNAL_MESSAGE = "Ha ocurrido un error interno. Usa el request_id para reportarlo."
_INVALID_REQUEST_MESSAGE = "La peticion no cumple el esquema esperado."

# La unica ruta que habla un protocolo ajeno (RFC-0005 13).
_RUTA_OPEN_RESPONSES = "/v1/responses"

# Codigos de RFC-0005 8, por estado HTTP. Un estado no listado cae en
# `internal_error`: es preferible un codigo generico a inventar uno.
_CODES: dict[int, str] = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    413: "payload_too_large",
    429: "rate_limited",
    500: "internal_error",
    503: "upstream_unavailable",
    504: "timeout",
}


def error_body(code: str, message: str, request_id: str) -> dict[str, Any]:
    """Cuerpo de error de RFC-0005 8."""
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def new_request_id() -> str:
    """Identificador de correlacion (ULID) -- RFC-0005 8."""
    return f"req_{ULID()}"


def current_request_id(request: Request) -> str:
    """El `request_id` que el middleware adjunto a esta peticion."""
    identificador = getattr(request.state, _REQUEST_ID_STATE, None)
    # Sin middleware no hay correlacion posible; se genera uno antes que
    # devolver vacio, para que el cuerpo de error nunca salga sin el.
    return identificador if identificador else new_request_id()


async def request_id_middleware(request: Request, call_next: Any) -> Response:
    """Genera el `request_id`, lo publica en el contexto de logging y lo
    devuelve en la cabecera `X-Request-ID` (RFC-0005 8, CA-12)."""
    identificador = new_request_id()
    setattr(request.state, _REQUEST_ID_STATE, identificador)
    testigo = _request_id.set(identificador)
    try:
        respuesta: Response = await call_next(request)
    finally:
        # Se restaura siempre, tambien si el turno revienta: un contexto que
        # sobrevive a su peticion correlaciona al incidente equivocado, que
        # es peor que no correlacionar.
        _request_id.reset(testigo)
    respuesta.headers[REQUEST_ID_HEADER] = identificador
    return respuesta


def _instalar_filtro_de_correlacion() -> None:
    """Pone `RequestIdFilter` en la raiz, una sola vez.

    En la raiz y no en un logger concreto: CA-12 dice "todas las lineas", y
    enumerar los loggers de la aplicacion garantizaria que el proximo modulo
    se quede fuera sin que nadie lo note.

    Un `logging.Filter` en un logger solo ve lo que ese logger emite, no lo
    que le llega por propagacion de los hijos -- por eso el filtro va
    tambien en los handlers de la raiz, que si ven todo el arbol.
    """
    raiz = logging.getLogger()
    if not any(isinstance(f, RequestIdFilter) for f in raiz.filters):
        raiz.addFilter(RequestIdFilter())
    for handler in raiz.handlers:
        if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
            handler.addFilter(RequestIdFilter())


def _respuesta(
    request: Request, status: int, message: str, extra_headers: Mapping[str, str] | None = None
) -> JSONResponse:
    identificador = current_request_id(request)
    # Las cabeceras del `HTTPException` viajan con la respuesta: el `429` de
    # RFC-0005 7 no sirve de nada sin `Retry-After` y `X-RateLimit-*`.
    cabeceras = {**(extra_headers or {}), REQUEST_ID_HEADER: identificador}
    codigo = _CODES.get(status, "internal_error")
    cuerpo = error_body(codigo, message, identificador)
    return JSONResponse(
        status_code=status,
        content=cuerpo | _forma_open_responses(request, codigo, message),
        headers=cabeceras,
    )


def _forma_open_responses(request: Request, codigo: str, message: str) -> dict[str, Any]:
    """Las claves hermanas que exige Open Responses (RFC-0005 13.5, CA-23).

    Se emiten **ademas** del cuerpo de 8, no en su lugar: un cliente que ya
    lea el formato propio no debe romperse porque otro cliente hable la
    especificacion. `code` y `message` se duplican a proposito -- son el
    mismo valor en los dos sitios--, y `request_id` vive solo dentro de
    `error` porque no pertenece a la especificacion.

    Solo en `/v1/responses`: anadirlas en todas partes convertiria una
    concesion a un protocolo externo en el formato de error del sistema.
    """
    if not request.url.path.startswith(_RUTA_OPEN_RESPONSES):
        return {}
    return {"type": "error", "code": codigo, "message": message}


def install_error_handling(app: FastAPI) -> None:
    """Registra el middleware de correlacion y los manejadores que fuerzan
    el formato de 8 en toda respuesta de error."""
    app.middleware("http")(request_id_middleware)
    _instalar_filtro_de_correlacion()

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # `detail` lo escribimos nosotros al lanzar el HTTPException, o lo
        # pone Starlette ("Not Found"): en ningun caso trae interno.
        return _respuesta(request, exc.status_code, str(exc.detail), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
        # RFC-0005 8: esquema invalido es `400 invalid_request`, no el `422`
        # con `detail` que FastAPI devuelve por defecto -- ese codigo no
        # esta en la tabla de 8. Tampoco se publica `exc.errors()`: lleva la
        # ruta del campo y el tipo esperado, que es superficie de mas (I-6).
        return _respuesta(request, 400, _INVALID_REQUEST_MESSAGE)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # No se mira `exc`: su texto es justo lo que I-6 prohibe publicar.
        return _respuesta(request, 500, _INTERNAL_MESSAGE)
