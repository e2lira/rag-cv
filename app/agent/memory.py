"""Memoria de conversacion -- RFC-0004 7.

Se persiste en PostgreSQL (conversations, messages -- RFC-0006). Los
resultados de herramientas de turnos anteriores NUNCA se reenvian: solo el
texto de las respuestas -- el contexto recuperado se vuelve a buscar si
hace falta. Reenviarlo multiplicaria los tokens de entrada por turno y
arrastraria contexto obsoleto tras una reindexacion.
"""

from psycopg import Connection

_CARACTERES_POR_TOKEN = 4  # aproximacion -- RFC-0004 7 no exige un tokenizer exacto aqui


def load_history(
    conn: Connection,
    conversation_id: str,
    *,
    max_turns: int = 6,
    token_budget: int = 2000,
) -> list[dict[str, str]]:
    """Ultimos max_turns pares usuario/asistente de conversation_id, del
    mas antiguo al mas reciente. Si excede token_budget se recortan los
    turnos mas antiguos primero -- este metodo solo trae historial PREVIO,
    nunca el turno actual, asi que ese nunca se recorta (RFC-0004 7)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = %(conversation_id)s "
            "ORDER BY created_at DESC LIMIT %(limite)s",
            {"conversation_id": conversation_id, "limite": max_turns * 2},
        )
        filas = cur.fetchall()
        conn.rollback()

    mensajes = [{"role": role, "content": content} for role, content in reversed(filas)]

    presupuesto_caracteres = token_budget * _CARACTERES_POR_TOKEN
    total = sum(len(m["content"]) for m in mensajes)
    while len(mensajes) > 1 and total > presupuesto_caracteres:
        descartado = mensajes.pop(0)
        total -= len(descartado["content"])

    return mensajes


def record_turn(
    conn: Connection,
    conversation_id: str,
    *,
    user_text: str,
    assistant_text: str,
    prompt_version: int,
    source_chunk_ids: list[int] | None = None,
    status: str = "ok",
    grounded: bool | None = None,
    model_id: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    tool_calls: int | None = None,
    cost_usd: float | None = None,
    latency_ms: int | None = None,
    request_id: str | None = None,
    message_id: str | None = None,
) -> str:
    """Persiste el par usuario/asistente de un turno -- RFC-0004 7. La
    version del prompt viaja en el mensaje del asistente (CA-9): es su
    respuesta la que se genero con esa version, no la pregunta.

    Devuelve el id del mensaje del asistente, que RFC-0005 4 publica como
    `message_id`: es el identificador que un usuario aporta para investigar
    un incidente, asi que tiene que ser el de la fila real y no uno nuevo.

    Los campos de medicion son opcionales porque RFC-0004 no los conoce --
    los aporta el turno de RFC-0005, que es quien mide-- y un turno sin
    ellos sigue siendo un turno valido.

    `message_id` se puede imponer porque el flujo SSE (RFC-0005 5) publica
    el identificador del turno en su primer evento, antes de que exista la
    fila: un cliente que aborta a mitad necesita poder nombrar el turno que
    abandono. Sin imponerlo habria que inventar un id y reconciliarlo
    despues, que es la clase de "casi el mismo" que acaba mintiendo.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content, status) "
            "VALUES (%(conversation_id)s, 'user', %(texto)s, 'ok')",
            {"conversation_id": conversation_id, "texto": user_text},
        )
        cur.execute(
            "INSERT INTO messages "
            "(id, conversation_id, role, content, prompt_version, source_chunk_ids, status, "
            " grounded, model_id, input_tokens, output_tokens, tool_calls, cost_usd, "
            " latency_ms, request_id) "
            "VALUES "
            "(COALESCE(%(id)s, gen_random_uuid()), "
            " %(conversation_id)s, 'assistant', %(texto)s, %(version)s, %(chunks)s, %(status)s, "
            " %(grounded)s, %(model_id)s, %(input_tokens)s, %(output_tokens)s, %(tool_calls)s, "
            " %(cost_usd)s, %(latency_ms)s, %(request_id)s) "
            "RETURNING id",
            {
                "id": message_id,
                "conversation_id": conversation_id,
                "texto": assistant_text,
                "version": prompt_version,
                "chunks": source_chunk_ids or [],
                "status": status,
                "grounded": grounded,
                "model_id": model_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "tool_calls": tool_calls,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
                "request_id": request_id,
            },
        )
        fila = cur.fetchone()
        cur.execute(
            "UPDATE conversations SET last_seen_at = now(), turns = turns + 1 "
            "WHERE id = %(conversation_id)s",
            {"conversation_id": conversation_id},
        )
    conn.commit()
    assert fila is not None  # RETURNING de un INSERT que no fallo
    return str(fila[0])
