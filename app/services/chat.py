"""Turno de conversacion -- RFC-0005 4 y 5, orquestacion (RFC-0001 4).

Vive aqui y no en `app/api/` porque el turno es logica de negocio: decidir
si la conversacion es de esa clave, invocar al agente, medir, persistir. La
capa API solo valida el esquema, traduce a codigos HTTP y serializa.

**Un solo camino para los tres transportes.** `run_turn_events` es la unica
implementacion del turno; `/v1/chat` la consume entera y `/v1/chat/stream` y
`/v1/responses` la traducen a su formato evento a evento. No es elegancia:
RFC-0005 13 declara **defecto** cualquier diferencia de comportamiento entre
las tres superficies para la misma pregunta, y dos implementaciones paralelas
divergen tarde o temprano sin que nada falle.
"""

import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from psycopg_pool import ConnectionPool
from strands import Agent
from strands.types.content import Message

from app.agent.builder import AgentFactory
from app.agent.memory import load_history, record_turn
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


class TurnFailed(Exception):
    """El flujo del agente termino en `error` -- RFC-0004 9.

    Lleva el `code` del evento para que la capa HTTP lo traduzca al codigo
    de RFC-0005 8 que corresponda (`timeout` -> 504), en vez de aplanar
    todo a un 500 que no dice nada.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


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


def _agente_del_turno(pool: ConnectionPool, factory: AgentFactory, conversation_id: str) -> Agent:
    """El agente de este turno, con el historial de esta conversacion.

    Aqui es donde RFC-0004 7 se vuelve cierto: hasta ADR-0017 `load_history`
    existia y no la llamaba nadie, asi que la continuidad que se observaba
    era la fuga del agente compartido, no la memoria.

    `load_history` devuelve solo el TEXTO de los turnos previos, nunca los
    resultados de herramientas (RFC-0004 7): reenviarlos multiplicaria los
    tokens de entrada y arrastraria contexto obsoleto tras una reindexacion.
    """
    with pool.connection(timeout=_TIEMPO_DE_ESPERA_DE_CONEXION) as conn:
        historial = load_history(conn, conversation_id)

    # `load_history` devuelve `role` como `str`; el contrato de strands lo
    # quiere acotado a user/assistant, que es justo lo que el CHECK de la
    # tabla `messages` ya garantiza (RFC-0006 4).
    mensajes: list[Message] = [
        {
            "role": "user" if m["role"] == "user" else "assistant",
            "content": [{"text": m["content"]}],
        }
        for m in historial
    ]
    return factory.for_turn(mensajes)


def model_id_of(agent: Agent) -> str | None:
    """El modelo **realmente** usado, no el configurado (RFC-0005 4, CA-16).

    Se pregunta al agente en vez de leer la configuracion porque el Model
    Loop puede haber conmutado por indisponibilidad (RFC-0013): reportar el
    configurado seria afirmar algo falso sobre quien respondio.
    """
    configuracion: dict[str, Any] = getattr(agent.model, "get_config", lambda: {})() or {}
    identificador = configuracion.get("model_id")
    return str(identificador) if identificador else None


async def run_turn_events(
    pool: ConnectionPool,
    factory: AgentFactory,
    *,
    message: str,
    conversation_id: str | None,
    key_id: str,
    request_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """El turno completo como flujo de eventos de RFC-0005 5.

    Recibe la **fabrica**, no un agente (ADR-0017): el agente se construye
    aqui, para este turno y con el historial de esta conversacion. Un agente
    de vida larga acumularia los mensajes de todos los usuarios.

    El `message_id` se acuna **antes** del primer evento y se impone a la
    fila al persistir: `start` lo publica para que un cliente que aborta a
    mitad pueda nombrar el turno que abandono.
    """
    conversacion = resolve_conversation(pool, conversation_id=conversation_id, key_id=key_id)
    agent = _agente_del_turno(pool, factory, conversacion)
    message_id = str(uuid.uuid4())
    yield {
        "event": "start",
        "data": {"conversation_id": conversacion, "message_id": message_id},
    }

    partes: list[str] = []
    fuentes: list[dict[str, Any]] = []
    consumo: dict[str, Any] = {}
    inicio = time.monotonic()

    async for evento in stream_turn(agent, message):
        tipo = evento.get("type")
        if tipo == "token":
            partes.append(evento["text"])
            yield {"event": "token", "data": {"text": evento["text"]}}
        elif tipo in ("tool_start", "tool_end"):
            yield {"event": tipo, "data": {k: v for k, v in evento.items() if k != "type"}}
        elif tipo == "sources":
            fuentes = list(evento["chunks"])
            yield {"event": "sources", "data": {"sources": fuentes}}
        elif tipo == "done":
            consumo = dict(evento.get("usage") or {})
        elif tipo == "error":
            # El turno fallido tambien se registra (RFC-0004 7): un turno que
            # no deja rastro es un incidente que no se puede investigar.
            _persistir(
                pool,
                conversacion,
                message_id=message_id,
                message=message,
                texto="".join(partes),
                fuentes=fuentes,
                consumo=consumo,
                agent=agent,
                latencia_ms=int((time.monotonic() - inicio) * 1000),
                request_id=request_id,
                status="failed",
            )
            codigo = str(evento.get("code") or "internal_error")
            yield {"event": "error", "data": {"error": {"code": codigo}}}
            return

    latencia_ms = int((time.monotonic() - inicio) * 1000)
    turno = _persistir(
        pool,
        conversacion,
        message_id=message_id,
        message=message,
        texto="".join(partes),
        fuentes=fuentes,
        consumo=consumo,
        agent=agent,
        latencia_ms=latencia_ms,
        request_id=request_id,
    )
    yield {
        "event": "done",
        "data": {"usage": turno.usage, "grounded": turno.grounded},
        "turn": turno,
    }


def _persistir(
    pool: ConnectionPool,
    conversacion: str,
    *,
    message_id: str,
    message: str,
    texto: str,
    fuentes: list[dict[str, Any]],
    consumo: dict[str, Any],
    agent: Agent,
    latencia_ms: int,
    request_id: str | None,
    status: str = "ok",
) -> TurnResult:
    """Deja el turno en la base y devuelve lo que las tres superficies publican."""
    modelo = model_id_of(agent)
    entrada = int(consumo.get("input_tokens", 0))
    salida = int(consumo.get("output_tokens", 0))
    llamadas = int(consumo.get("tool_calls", 0))
    coste = cost_usd(modelo or "", input_tokens=entrada, output_tokens=salida)
    # `grounded` es la ausencia de fuentes, no una opinion sobre el texto:
    # permite al cliente -- y a la evaluacion de RFC-0009 -- distinguir "no
    # se" de "se" sin leer la respuesta (RFC-0005 4).
    fundamentado = bool(fuentes)

    with pool.connection(timeout=_TIEMPO_DE_ESPERA_DE_CONEXION) as conn:
        record_turn(
            conn,
            conversacion,
            user_text=message,
            assistant_text=texto,
            prompt_version=SYSTEM_PROMPT_VERSION,
            source_chunk_ids=[int(f["chunk_id"]) for f in fuentes if "chunk_id" in f],
            status=status,
            grounded=fundamentado,
            model_id=modelo,
            input_tokens=entrada,
            output_tokens=salida,
            tool_calls=llamadas,
            cost_usd=coste,
            latency_ms=latencia_ms,
            request_id=request_id,
            message_id=message_id,
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
            "tool_calls": llamadas,
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


async def run_turn(
    pool: ConnectionPool,
    factory: AgentFactory,
    *,
    message: str,
    conversation_id: str | None,
    key_id: str,
    request_id: str | None = None,
) -> TurnResult:
    """El mismo turno, consumido entero -- RFC-0005 4.

    Consume `run_turn_events` en vez de invocar al agente por su cuenta: si
    `/v1/chat` tuviera su propio camino, podria divergir del flujo sin que
    nada fallara (RFC-0005 13).
    """
    turno: TurnResult | None = None
    async for evento in run_turn_events(
        pool,
        factory,
        message=message,
        conversation_id=conversation_id,
        key_id=key_id,
        request_id=request_id,
    ):
        if evento["event"] == "error":
            raise TurnFailed(str(evento["data"]["error"]["code"]))
        if evento["event"] == "done":
            turno = evento["turn"]

    assert turno is not None  # el flujo termina en `done` o en `error`
    return turno
