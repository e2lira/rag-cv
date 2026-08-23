"""Pool de conexiones -- RFC-0006 6."""

import psycopg
from psycopg_pool import ConnectionPool


def build_pool(
    conninfo: str,
    *,
    min_size: int = 2,
    max_size: int = 5,
    statement_timeout_ms: int = 5000,
    idle_in_transaction_timeout_ms: int = 10000,
) -> ConnectionPool:
    """RFC-0006 6: statement_timeout=5s a nivel de sesion de la aplicacion,
    idle_in_transaction_session_timeout=10s -- una transaccion olvidada no
    debe bloquear VACUUM. Los valores por defecto son los de DEV (2-5)."""

    def _configure(conn: psycopg.Connection) -> None:
        # autocommit=True: el reset del pool hace ROLLBACK al devolver una
        # conexion, lo que revertiria estos SET si quedaran en transaccion.
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {statement_timeout_ms}")
            cur.execute(
                f"SET idle_in_transaction_session_timeout = {idle_in_transaction_timeout_ms}"
            )
        conn.autocommit = False

    return ConnectionPool(
        conninfo,
        min_size=min_size,
        max_size=max_size,
        configure=_configure,
        open=True,
    )
