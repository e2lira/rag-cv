"""RFC-0019 7.1 y 5: la tabla del latido y el indice de reclamacion.

El contrato de forma (columnas, restricciones, indexdef) lo verifica
`test_migrations.py`, que compara el esquema entero. Aqui se prueba lo que
una comparacion de catalogo no ve: que `ck_watcher_outcome` RECHAZA de
verdad un resultado fuera de los cinco, y que el latido es de una fila por
`object_key`.
"""

import psycopg
import pytest

pytestmark = pytest.mark.integration


def test_outcome_check_rejects_unknown_value(database_url: str) -> None:
    """RFC-0019 7.1: los cinco valores de ck_watcher_outcome son cerrados."""
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        with pytest.raises(psycopg.errors.CheckViolation):
            cur.execute(
                "INSERT INTO watcher_heartbeat (object_key, last_run_at, last_outcome) "
                "VALUES (%s, now(), %s)",
                ("/opt/rag-cv/corpus/cv.md", "todo_bien"),
            )


def test_outcome_check_accepts_the_five(database_url: str) -> None:
    """Los cinco valores del contrato entran sin excepcion."""
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        for idx, outcome in enumerate(
            ("no_change", "indexed", "unstable", "missing_corpus", "failed")
        ):
            cur.execute(
                "INSERT INTO watcher_heartbeat (object_key, last_run_at, last_outcome) "
                "VALUES (%s, now(), %s)",
                (f"/opt/rag-cv/corpus/cv-{idx}.md", outcome),
            )

        cur.execute("SELECT count(*) FROM watcher_heartbeat")
        row = cur.fetchone()

    assert row is not None
    assert row[0] == 5


def test_heartbeat_is_one_row_per_object_key(database_url: str) -> None:
    """RFC-0019 7.1: `object_key` es la clave primaria -- el latido se
    actualiza en sitio, no se acumula una fila por ejecucion."""
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO watcher_heartbeat (object_key, last_run_at, last_outcome) "
            "VALUES (%s, now(), %s)",
            ("/opt/rag-cv/corpus/cv.md", "no_change"),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                "INSERT INTO watcher_heartbeat (object_key, last_run_at, last_outcome) "
                "VALUES (%s, now(), %s)",
                ("/opt/rag-cv/corpus/cv.md", "indexed"),
            )


def test_last_success_at_is_nullable(database_url: str) -> None:
    """RFC-0019 7.1: `last_run_at` se escribe siempre; `last_success_at` solo
    cuando el ciclo termina bien, asi que admite NULL desde el primer ciclo."""
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO watcher_heartbeat (object_key, last_run_at, last_outcome) "
            "VALUES (%s, now(), %s) RETURNING last_success_at",
            ("/opt/rag-cv/corpus/cv.md", "failed"),
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] is None
