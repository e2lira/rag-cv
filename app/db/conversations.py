"""Conversaciones: creacion y pertenencia -- RFC-0005 6.3.

La pertenencia se resuelve **en el WHERE**, no comparando en Python despues
de leer la fila. La diferencia importa: una consulta que trae la conversacion
y luego decide, en algun momento tuvo en memoria una conversacion ajena, y
basta un `return` mal puesto para publicarla. Filtrando por `key_id` la fila
ajena no llega nunca.
"""

from psycopg import Connection


def create_conversation(conn: Connection, *, key_id: str, locale: str | None = None) -> str:
    """Crea la conversacion de una clave y devuelve su id (RFC-0005 4)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO conversations (key_id, locale) VALUES (%s, %s) RETURNING id",
            (key_id, locale),
        )
        fila = cur.fetchone()
    conn.commit()
    assert fila is not None  # RETURNING de un INSERT que no fallo
    return str(fila[0])


def conversation_belongs_to(conn: Connection, *, conversation_id: str, key_id: str) -> bool:
    """Si esa conversacion es de esa clave (RFC-0005 6.3).

    Devuelve lo mismo para "no existe" y para "es de otra clave", y la capa
    HTTP responde `404` en los dos casos: un `403` confirmaria que el
    recurso existe, y eso ya es informacion sobre las conversaciones de
    otro (CA-8).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM conversations WHERE id = %s AND key_id = %s",
            (conversation_id, key_id),
        )
        return cur.fetchone() is not None


def conversation_of_message(conn: Connection, *, message_id: str, key_id: str) -> str | None:
    """La conversacion de un mensaje, si es de esa clave (RFC-0005 13.1).

    Lo usa `previous_response_id`, que nombra una respuesta y tiene que
    continuar **su** conversacion. El `key_id` va en el mismo `WHERE` por la
    razon de `conversation_belongs_to`: la fila ajena no llega nunca.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT m.conversation_id FROM messages m "
            "JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.id = %s AND c.key_id = %s",
            (message_id, key_id),
        )
        fila = cur.fetchone()
        return str(fila[0]) if fila else None
