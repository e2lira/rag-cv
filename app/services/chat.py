"""Turno de conversacion -- RFC-0005 4, orquestacion (RFC-0001 4).

Vive aqui y no en `app/api/` porque el turno es logica de negocio: decidir
si la conversacion es de esa clave, invocar al agente, medir, persistir. La
capa API solo valida el esquema, traduce a codigos HTTP y pone cabeceras.

**Un solo camino para los tres transportes.** `/v1/chat` consume el turno
entero; `/v1/chat/stream` y `/v1/responses` consumen el mismo flujo de
eventos y lo traducen a su formato. Cualquier diferencia de comportamiento
entre ellos seria un defecto, no una variante (RFC-0005 13).
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from psycopg_pool import ConnectionPool
from strands import Agent

from app.agent.memory import record_turn
from app.agent.prompts import SYSTEM_PROMPT_VERSION
from app.agent.streaming import stream_turn
from app.core.pricing import cost_usd
from app.db.conversations import conversation_belongs_to, create_conversation

_TIEMPO_DE_ESPERA_DE_CONEXION = 5.0


class ConversationNotFound(Exception):
    """La conversacion no existe o es de otra clave -- RFC-0005 6.3, CA-8.

    Una sola excepcion para los dos casos, a proposito: distinguirlos en la
    respuesta confirmaria la existencia del recurso ajeno, que es justo lo
    que el `404` de CA-8 evita.
    """


@dataclass
class TurnResult:
    """Lo que un turno produce, antes de vestirse de HTTP."""

    conversation_id: str
    message_id: str
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    grounded: bool = False
    usage: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


def resolve_conversation(pool: ConnectionPool, *, conversation_id: str | None, key_id: str) -> str:
    """Devuelve la conversacion de la peticion, creandola si no venia.

    Si venia y no es de esta clave, `ConversationNotFound` -- y la capa HTTP
    responde `404`, no `403` (RFC-0005 6.3, CA-8).
    """
    with pool.connection(timeout=_TIEMPO_DE_ESPERA_DE_CONEXION) as conn:
        if conversation_id is None:
            return create_conversation(conn, key_id=key_id)
        if not conversation_belongs_to(conn, conversation_id=conversation_id, key_id=key_id):
            raise ConversationNotFound(conversation_id)
        return conversation_id


def model_id_of(agent: Agent) -> str | None:
    """El modelo **realmente** usado, no el configurado (RFC-0005 4, CA-16).

    Se pregunta al agente en vez de leer la configuracion porque el Model
    Loop puede haber conmutado por indisponibilidad (RFC-0013): reportar el
    configurado seria afirmar algo falso sobre quien respondio.
    """
    configuracion: dict[str, Any] = getattr(agent.model, "get_config", lambda: {})() or {}
    identificador = configuracion.get("model_id")
    return str(identificador) if identificador else None


async def collect_turn(
    agent: Agent, message: str
) -> tuple[str, list[dict[str, Any]], dict[str, Any], str | None]:
    """Consume el flujo del agente hasta `done` y devuelve el turno completo.

    El texto se acumula de los eventos `token`, que es el mismo flujo que
    consume `/v1/chat/stream`: si `/v1/chat` invocara al agente por otro
    camino, las dos superficies podrian divergir sin que nada fallara.
    """
    partes: list[str] = []
    fuentes: list[dict[str, Any]] = []
    consumo: dict[str, Any] = {}
    error: str | None = None

    async for evento in stream_turn(agent, message):
        tipo = evento.get("type")
        if tipo == "token":
            partes.append(evento["text"])
        elif tipo == "sources":
            fuentes = list(evento["chunks"])
        elif tipo == "done":
            consumo = dict(evento.get("usage") or {})
        elif tipo == "error":
            error = str(evento.get("code") or "internal_error")

    return "".join(partes), fuentes, consumo, error


async def run_turn(
    pool: ConnectionPool,
    agent: Agent,
    *,
    message: str,
    conversation_id: str | None,
    key_id: str,
    request_id: str | None = None,
) -> TurnResult:
    """Un turno completo: conversacion, agente, medicion y persistencia."""
    conversacion = resolve_conversation(pool, conversation_id=conversation_id, key_id=key_id)

    inicio = time.monotonic()
    texto, fuentes, consumo, error = await collect_turn(agent, message)
    latencia_ms = int((time.monotonic() - inicio) * 1000)

    if error is not None:
        raise TurnFailed(error)

    modelo = model_id_of(agent)
    entrada = int(consumo.get("input_tokens", 0))
    salida = int(consumo.get("output_tokens", 0))
    coste = cost_usd(modelo or "", input_tokens=entrada, output_tokens=salida)
    # `grounded` es la ausencia de fuentes, no una opinion sobre el texto:
    # permite al cliente -- y a la evaluacion de RFC-0009 -- distinguir "no
    # se" de "se" sin leer la respuesta (RFC-0005 4).
    fundamentado = bool(fuentes)

    with pool.connection(timeout=_TIEMPO_DE_ESPERA_DE_CONEXION) as conn:
        message_id = record_turn(
            conn,
            conversacion,
            user_text=message,
            assistant_text=texto,
            prompt_version=SYSTEM_PROMPT_VERSION,
            source_chunk_ids=[int(f["chunk_id"]) for f in fuentes if "chunk_id" in f],
            grounded=fundamentado,
            model_id=modelo,
            input_tokens=entrada,
            output_tokens=salida,
            tool_calls=int(consumo.get("tool_calls", 0)),
            cost_usd=coste,
            latency_ms=latencia_ms,
            request_id=request_id,
        )

    return TurnResult(
        conversation_id=conversacion,
        message_id=message_id,
        answer=texto,
        sources=fuentes,
        grounded=fundamentado,
        usage={
            "input_tokens": entrada,
            "output_tokens": salida,
            "tool_calls": int(consumo.get("tool_calls", 0)),
            "cost_usd": coste,
            "latency_ms": latencia_ms,
        },
        meta={
            "model_id": modelo,
            "prompt_version": SYSTEM_PROMPT_VERSION,
            # Degradado es lo que el retrieval declara por fragmento
            # (RFC-0003): si algun fragmento vino de la rama de respaldo, el
            # turno entero se sirvio degradado y el cliente merece saberlo.
            "degraded": any(bool(f.get("degraded")) for f in fuentes),
        },
    )


class TurnFailed(Exception):
    """El flujo del agente termino en `error` -- RFC-0004 9.

    Lleva el `code` del evento para que la capa HTTP lo traduzca al codigo
    de RFC-0005 8 que corresponda (`timeout` -> 504), en vez de aplanar
    todo a un 500 que no dice nada.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def stream_events(agent: Agent, message: str) -> AsyncIterator[dict[str, Any]]:
    """El flujo crudo del agente, para los transportes de RFC-0005 5 y 13.4."""
    async for evento in stream_turn(agent, message):
        yield evento
