"""Comprobaciones de arranque -- RFC-0006 7."""

import psycopg


class StartupCheckError(RuntimeError):
    """Aborta el arranque de la aplicacion -- RFC-0006 7."""


def check_embedding_dimension(conn: psycopg.Connection, expected_dim: int) -> None:
    """RFC-0006 7 #3: la dimension de cv_chunks.embedding debe coincidir con
    EMBEDDING_DIM. pgvector guarda la dimension declarada en el atttypmod de
    la columna, sin desplazamiento (a diferencia de NUMERIC)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'cv_chunks'::regclass AND attname = 'embedding'"
        )
        row = cur.fetchone()

    actual_dim = row[0] if row else None
    if actual_dim != expected_dim:
        raise StartupCheckError(
            f"cv_chunks.embedding tiene dimension {actual_dim}, se esperaba "
            f"{expected_dim} (RFC-0006 7 #3)"
        )


def check_single_embed_model(conn: psycopg.Connection, expected_model_id: str) -> None:
    """RFC-0006 7 #4: un unico embed_model_id en la tabla, y debe coincidir
    con la configuracion activa. Una tabla vacia (sin indexar aun) pasa."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT embed_model_id FROM cv_chunks")
        model_ids = {row[0] for row in cur.fetchall()}

    if len(model_ids) > 1:
        raise StartupCheckError(
            f"cv_chunks mezcla varios embed_model_id: {sorted(model_ids)} (RFC-0006 7 #4)"
        )
    if model_ids and next(iter(model_ids)) != expected_model_id:
        raise StartupCheckError(
            f"cv_chunks.embed_model_id={next(iter(model_ids))!r} no coincide con "
            f"la configuracion activa {expected_model_id!r} (RFC-0006 7 #4)"
        )
