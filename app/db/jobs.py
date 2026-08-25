"""Trabajos de ingesta -- RFC-0005 3.2 sobre el esquema de RFC-0006 4.

La idempotencia **no la garantiza este codigo**: la garantiza el
`UNIQUE (idempotency_key)` de `ingestion_jobs`. Aqui solo se forma la misma
clave determinista que RFC-0019 7 (`{object_key}@{source_version_id}`) y se
inserta con `ON CONFLICT DO NOTHING`. Si la garantia viviera en un `if` de
Python, dos peticiones simultaneas encolarian dos trabajos.
"""

from typing import Any

from psycopg import Connection


class NoCurrentCorpus(Exception):
    """No hay exactamente una version vigente que reindexar (RFC-0019 3)."""


def enqueue_reindex(conn: Connection) -> tuple[str, str]:
    """Encola la reindexacion del corpus vigente. Devuelve `(job_id, state)`.

    Encola, **no ejecuta** (RFC-0005 3.2): la ingesta la corre el proceso de
    RFC-0019 desde el `crontab`, y la API que atiende consultas no debe
    bloquearse reindexando.

    Cual es el corpus vigente lo dice el *ledger*, no la configuracion: si
    se leyera `CORPUS_PATH` se podria encolar la reindexacion de un archivo
    que el proceso de RFC-0019 nunca registro, y el trabajo moriria en el
    `crontab` sin que la API lo supiera.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, object_key, source_version_id FROM source_documents WHERE is_current"
        )
        vigentes = cur.fetchall()
        # Ni cero ni varias: con varias no habria forma de saber cual quiso
        # reindexar el operador, y elegir una en silencio seria peor que
        # decir que no se puede.
        if len(vigentes) != 1:
            raise NoCurrentCorpus(f"{len(vigentes)} versiones vigentes")
        documento_id, object_key, version_id = (
            str(vigentes[0][0]),
            str(vigentes[0][1]),
            str(vigentes[0][2]),
        )

        clave = f"{object_key}@{version_id}"
        cur.execute(
            "INSERT INTO ingestion_jobs "
            "(idempotency_key, object_key, source_version_id, source_document_id) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (idempotency_key) DO NOTHING",
            (clave, object_key, version_id, documento_id),
        )
        # Se vuelve a leer en vez de usar RETURNING: con DO NOTHING el
        # INSERT no devuelve fila cuando el trabajo ya existia, y ese es
        # justo el caso que CA-24 exige atender con el MISMO job_id.
        cur.execute(
            "SELECT id, job_state FROM ingestion_jobs WHERE idempotency_key = %s",
            (clave,),
        )
        fila = cur.fetchone()
    conn.commit()
    assert fila is not None  # o se inserto, o ya estaba
    return str(fila[0]), str(fila[1])


def get_job(conn: Connection, *, job_id: str) -> dict[str, Any] | None:
    """El estado de un trabajo, o `None` si no existe (RFC-0005 3.2)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, job_state, attempt_count, error_code, started_at, completed_at "
            "FROM ingestion_jobs WHERE id = %s",
            (job_id,),
        )
        fila = cur.fetchone()
        conn.rollback()

    if fila is None:
        return None
    return {
        "job_id": str(fila[0]),
        "state": str(fila[1]),
        "attempt_count": int(fila[2]),
        # `error_detail` NO se publica (invariante I-6): lleva el texto del
        # fallo, que puede arrastrar rutas y SQL. El codigo basta para saber
        # que paso.
        "error_code": fila[3],
        "started_at": fila[4].isoformat() if fila[4] else None,
        "completed_at": fila[5].isoformat() if fila[5] else None,
    }
