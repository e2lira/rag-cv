"""Memoria de conversacion -- RFC-0004 7.

Se persiste en PostgreSQL (conversations, messages -- RFC-0006). Los
resultados de herramientas de turnos anteriores NUNCA se reenvian: solo el
texto de las respuestas -- el contexto recuperado se vuelve a buscar si
hace falta. Reenviarlo multiplicaria los tokens de entrada por turno y
arrastraria contexto obsoleto tras una reindexacion.
"""

from psycopg import Connection


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
    raise NotImplementedError  # RFC-0004 7: implementacion pendiente de su propio ciclo


def record_turn(
    conn: Connection,
    conversation_id: str,
    *,
    user_text: str,
    assistant_text: str,
    prompt_version: int,
    source_chunk_ids: list[int] | None = None,
    status: str = "ok",
) -> None:
    """Persiste el par usuario/asistente de un turno -- RFC-0004 7. La
    version del prompt viaja en el mensaje del asistente (CA-9): es su
    respuesta la que se genero con esa version, no la pregunta."""
    raise NotImplementedError  # RFC-0004 7 9: implementacion pendiente de su propio ciclo
