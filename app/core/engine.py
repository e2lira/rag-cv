"""Pool de conexiones -- RFC-0006 6."""

from psycopg_pool import ConnectionPool


def build_pool(
    conninfo: str,
    *,
    min_size: int = 2,
    max_size: int = 5,
    statement_timeout_ms: int = 5000,
    idle_in_transaction_timeout_ms: int = 10000,
) -> ConnectionPool:
    raise NotImplementedError
