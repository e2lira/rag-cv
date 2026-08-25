"""Esquemas de peticion y respuesta -- RFC-0005 4 (RFC-0001 4: solo validacion).

Los limites viven aqui y no en el servicio a proposito: un `message` vacio o
de 3 000 caracteres se rechaza **antes** de invocar al agente, que es lo
unico que cuesta dinero. Validar despues seria pagar por descubrir que la
peticion nunca fue valida.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MAX_MESSAGE_CHARS = 2000


class ChatRequest(BaseModel):
    """Cuerpo de `/v1/chat` y `/v1/chat/stream` (RFC-0005 4)."""

    message: Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_CHARS)]
    conversation_id: UUID | None = None
    locale: Literal["es", "en"] | None = None

    @field_validator("message")
    @classmethod
    def _no_vacio_tras_strip(cls, valor: str) -> str:
        """RFC-0005 4: "no vacio tras `strip()`". Sin esto, un mensaje de
        cien espacios pasa `min_length` y llega al modelo, que cobra por
        contestarle a nada."""
        limpio = valor.strip()
        if not limpio:
            raise ValueError("message no puede estar vacio")
        return limpio


class ChatResponse(BaseModel):
    """Respuesta 200 de `/v1/chat` (RFC-0005 4)."""

    conversation_id: str
    message_id: str
    answer: str
    sources: list[dict[str, Any]]
    grounded: bool
    usage: dict[str, Any]
    meta: dict[str, Any]
