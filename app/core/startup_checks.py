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


_REQUIRED_EXTENSIONS = ("vector", "unaccent", "pg_trgm")


def check_extensions_present(conn: psycopg.Connection) -> None:
    """RFC-0006 7 #1: vector, unaccent y pg_trgm deben estar instaladas."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT extname FROM pg_extension WHERE extname = ANY(%s)",
            (list(_REQUIRED_EXTENSIONS),),
        )
        installed = {row[0] for row in cur.fetchall()}

    missing = set(_REQUIRED_EXTENSIONS) - installed
    if missing:
        raise StartupCheckError(f"faltan extensiones requeridas: {sorted(missing)} (RFC-0006 7 #1)")


def _parse_version(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def check_pgvector_version(conn: psycopg.Connection, minimum: str = "0.8") -> None:
    """RFC-0006 7 #2: por debajo del minimo, HNSW y halfvec cambian entre
    versiones de pgvector."""
    with conn.cursor() as cur:
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        row = cur.fetchone()

    if row is None:
        raise StartupCheckError("la extension vector no esta instalada (RFC-0006 7 #2)")

    installed = row[0]
    if _parse_version(installed) < _parse_version(minimum):
        raise StartupCheckError(
            f"pgvector {installed} instalado, se requiere >= {minimum} (RFC-0006 7 #2)"
        )


def check_alembic_head(conn: psycopg.Connection, expected_head: str) -> None:
    """RFC-0006 7 #5: la base debe estar en la revision Alembic mas reciente."""
    with conn.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        row = cur.fetchone()

    actual_head = row[0] if row else None
    if actual_head != expected_head:
        raise StartupCheckError(
            f"la base esta en la revision {actual_head!r}, se esperaba "
            f"{expected_head!r} (RFC-0006 7 #5)"
        )
