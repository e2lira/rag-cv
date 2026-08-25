"""Transporte HTTP del turno -- RFC-0005 4 (RFC-0001 4: sin logica ni SQL).

Aqui solo hay tres cosas: la dependencia que autentica y acota, la traduccion
del resultado del servicio a la respuesta de 4, y la traduccion de sus fallos
a los codigos de 8. El turno lo orquesta `app/services/chat.py`.
"""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.exceptions import HTTPException

from app.api.deps import enforce_body_limit, rate_limiter, require_role
from app.api.errors import current_request_id
from app.api.schemas import ChatRequest, ChatResponse
from app.core.security import ApiKey
from app.services.chat import ConversationNotFound, TurnFailed, run_turn

router = APIRouter(prefix="/v1")

_NOT_FOUND_MESSAGE = "La conversacion no existe."
# El flujo del agente solo distingue el vencimiento (RFC-0004 9); lo demas
# es un fallo aguas arriba que no se puede clasificar mas fino sin mirar el
# SDK, y RFC-0004 10 prohibe clasificar por SDK.
_CODIGOS_HTTP = {"timeout": 504}


def _cuota(request: Request, response: Response, clave: ApiKey) -> None:
    """Aplica la cuota de la clave ya resuelta (RFC-0005 7).

    Se invoca desde el handler y no como `Depends` suelto porque el `key_id`
    solo existe **despues** de autenticar: montarlo estaticamente exigiria
    conocer la clave al construir la ruta.
    """
    rate_limiter(clave.id)(request, response)


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_body_limit)])
async def chat(
    peticion: ChatRequest,
    request: Request,
    response: Response,
    clave: ApiKey = Depends(require_role("read")),
) -> ChatResponse:
    """Un turno de conversacion (RFC-0005 4)."""
    _cuota(request, response, clave)

    try:
        turno = await run_turn(
            request.app.state.db_pool,
            request.app.state.agent,
            message=peticion.message,
            conversation_id=str(peticion.conversation_id) if peticion.conversation_id else None,
            key_id=clave.id,
            request_id=current_request_id(request),
        )
    except ConversationNotFound as exc:
        # 404 y no 403 (RFC-0005 6.3, CA-8): un 403 confirmaria que la
        # conversacion existe, y eso ya es informacion sobre las de otro.
        raise HTTPException(status_code=404, detail=_NOT_FOUND_MESSAGE) from exc
    except TurnFailed as exc:
        raise HTTPException(status_code=_CODIGOS_HTTP.get(exc.code, 503)) from exc

    # Cache-Control: no-store en /v1/* (RFC-0005 9): la respuesta lleva el
    # contenido de una conversacion privada; que un intermediario la guarde
    # es exponerla a quien no la pidio.
    response.headers["Cache-Control"] = "no-store"
    return ChatResponse(
        conversation_id=turno.conversation_id,
        message_id=turno.message_id,
        answer=turno.answer,
        sources=turno.sources,
        grounded=turno.grounded,
        usage=turno.usage,
        meta=turno.meta,
    )
