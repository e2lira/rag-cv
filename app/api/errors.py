"""Formato unico de error y correlacion de peticiones -- RFC-0005 8.

`app/api/` no contiene logica de negocio ni SQL (RFC-0001): esto es forma de
respuesta y cabeceras, nada mas.

Ningun cuerpo de error lleva trazas, SQL ni nombres de recursos internos
(invariante I-6). Lo unico que se le pide a un usuario para investigar un
incidente es el `request_id`, que ademas viaja en todos los logs del turno.
"""

from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from ulid import ULID

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_STATE = "rfc0005_request_id"

# El mensaje de 500 es fijo a proposito: cualquier detalle del fallo es
# exactamente lo que I-6 prohibe publicar.
_INTERNAL_MESSAGE = "Ha ocurrido un error interno. Usa el request_id para reportarlo."
_INVALID_REQUEST_MESSAGE = "La peticion no cumple el esquema esperado."

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
    """Genera el `request_id`, lo adjunta a la peticion y lo devuelve en la
    cabecera `X-Request-ID` (RFC-0005 8, CA-12)."""
    identificador = new_request_id()
    setattr(request.state, _REQUEST_ID_STATE, identificador)
    respuesta: Response = await call_next(request)
    respuesta.headers[REQUEST_ID_HEADER] = identificador
    return respuesta


def _respuesta(request: Request, status: int, message: str) -> JSONResponse:
    identificador = current_request_id(request)
    return JSONResponse(
        status_code=status,
        content=error_body(_CODES.get(status, "internal_error"), message, identificador),
        headers={REQUEST_ID_HEADER: identificador},
    )


def install_error_handling(app: FastAPI) -> None:
    """Registra el middleware de correlacion y los manejadores que fuerzan
    el formato de 8 en toda respuesta de error."""
    app.middleware("http")(request_id_middleware)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # `detail` lo escribimos nosotros al lanzar el HTTPException, o lo
        # pone Starlette ("Not Found"): en ningun caso trae interno.
        return _respuesta(request, exc.status_code, str(exc.detail))

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
