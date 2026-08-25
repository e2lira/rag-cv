"""Transporte Open Responses -- RFC-0005 13 (RFC-0001 4: sin logica ni SQL).

El turno es el mismo de `/v1/chat`; aqui solo se traduce el vocabulario. La
traduccion vive en `app/services/open_responses.py` y esta capa se limita a
codigos HTTP, cabeceras y serializacion.
"""

import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import enforce_body_limit, rate_limiter, require_role
from app.api.errors import current_request_id
from app.api.schemas import MAX_MESSAGE_CHARS, ResponsesRequest
from app.api.sse import SSE_HEADERS, SSE_MEDIA_TYPE, format_data
from app.core.security import ApiKey
from app.db.conversations import conversation_of_message
from app.services.chat import ConversationNotFound, TurnResult, run_turn_events
from app.services.open_responses import (
    extract_input,
    message_id_of,
    response_id,
    response_object,
)

router = APIRouter(prefix="/v1")

_INVALID_INPUT = "El campo `input` no trae ningun mensaje de rol user."
_NOT_FOUND = "La conversacion no existe."
_TIEMPO_DE_ESPERA = 5.0


@router.post("/responses", dependencies=[Depends(enforce_body_limit)])
async def responses(
    peticion: ResponsesRequest,
    request: Request,
    response: Response,
    clave: ApiKey = Depends(require_role("read")),
) -> Any:
    """Un turno, en el vocabulario de Open Responses (RFC-0005 13)."""
    rate_limiter(clave.id)(request, response)

    mensaje = _mensaje(peticion)
    conversacion = _conversacion(request, peticion, clave)
    request_id = current_request_id(request)

    if peticion.stream:
        return _flujo(request, clave, mensaje, conversacion, request_id, dict(response.headers))

    turno = await _turno(request, clave, mensaje, conversacion, request_id)
    response.headers["Cache-Control"] = "no-store"
    return JSONResponse(
        content=response_object(turno, created_at=int(time.time())),
        headers=dict(response.headers),
    )


def _mensaje(peticion: ResponsesRequest) -> str:
    """El texto del turno, con las mismas restricciones que `message` de 4."""
    try:
        mensaje = extract_input(peticion.input).strip()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=_INVALID_INPUT) from exc
    if not mensaje or len(mensaje) > MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=400, detail=_INVALID_INPUT)
    return mensaje


def _conversacion(request: Request, peticion: ResponsesRequest, clave: ApiKey) -> str | None:
    """Traduce `previous_response_id` a la conversacion que continua (13.1).

    Un identificador que no corresponde a ningun mensaje **de esta clave**
    es `404` por la misma razon que CA-8: distinguir "no existe" de "no es
    tuyo" seria el oraculo que el 404 cierra.
    """
    if peticion.previous_response_id is None:
        return None

    with request.app.state.db_pool.connection(timeout=_TIEMPO_DE_ESPERA) as conn:
        conversacion = conversation_of_message(
            conn, message_id=message_id_of(peticion.previous_response_id), key_id=clave.id
        )
    if conversacion is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return conversacion


async def _turno(
    request: Request, clave: ApiKey, mensaje: str, conversacion: str | None, request_id: str
) -> TurnResult:
    turno: TurnResult | None = None
    try:
        async for evento in run_turn_events(
            request.app.state.db_pool,
            request.app.state.agent,
            message=mensaje,
            conversation_id=conversacion,
            key_id=clave.id,
            request_id=request_id,
        ):
            if evento["event"] == "error":
                raise HTTPException(status_code=503, detail="El proveedor no esta disponible.")
            if evento["event"] == "done":
                turno = evento["turn"]
    except ConversationNotFound as exc:
        raise HTTPException(status_code=404, detail=_NOT_FOUND) from exc

    assert turno is not None  # el flujo termina en `done` o en `error`
    return turno


def _flujo(
    request: Request,
    clave: ApiKey,
    mensaje: str,
    conversacion: str | None,
    request_id: str,
    cabeceras: dict[str, str],
) -> StreamingResponse:
    """Streaming con los nombres de Open Responses, **no** los de 5 (13.4)."""

    async def _generar() -> AsyncIterator[str]:
        secuencia = 0
        identificador = ""
        async for evento in run_turn_events(
            request.app.state.db_pool,
            request.app.state.agent,
            message=mensaje,
            conversation_id=conversacion,
            key_id=clave.id,
            request_id=request_id,
        ):
            nombre = evento["event"]
            if nombre == "start":
                identificador = response_id(evento["data"]["message_id"])
                yield format_data(
                    {
                        "type": "response.created",
                        "response": {"id": identificador, "status": "in_progress"},
                    }
                )
            elif nombre == "token":
                secuencia += 1
                yield format_data(
                    {
                        "type": "response.output_text.delta",
                        "sequence_number": secuencia,
                        "item_id": f"msg_{message_id_of(identificador)}",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": evento["data"]["text"],
                    }
                )
            elif nombre == "done":
                # `response.completed` carga el objeto entero de 13.3, para
                # que un cliente que solo escuche este evento tenga la
                # respuesta con sus citas y su consumo.
                yield format_data(
                    {
                        "type": "response.completed",
                        "response": response_object(evento["turn"], created_at=int(time.time())),
                    }
                )
            elif nombre == "error":
                yield format_data(
                    {
                        "type": "error",
                        "code": evento["data"]["error"]["code"],
                        "message": "El turno no pudo completarse.",
                    }
                )
                return

    return StreamingResponse(
        _generar(),
        media_type=SSE_MEDIA_TYPE,
        headers={**SSE_HEADERS, **cabeceras},
    )
