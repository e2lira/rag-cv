"""Herramientas expuestas al agente -- RFC-0004 5.

search_cv y list_cv_sections son las UNICAS dos herramientas registradas
(A-6): nada de acceso a internet, ejecucion de codigo ni lectura de
archivos. La firma de cada una es parte del contrato -- es lo que el
modelo lee para decidir cuando llamarlas -- y no lleva parametros de
infraestructura (conexion, embedder): eso se resuelve aqui, perezosamente,
la primera vez que una herramienta se invoca (igual que build_model()
resuelve el proveedor a partir de Settings, sin que build_agent() se lo
pase por parametro).
"""

from datetime import date

import httpx2
from psycopg_pool import ConnectionPool
from strands import tool

from app.core.engine import build_pool
from app.core.settings import Settings
from app.retrieval.embedder import Embedder, build_embedder
from app.retrieval.formatter import format_context_block
from app.retrieval.hybrid import hybrid_search

_pool: ConnectionPool | None = None
_embedder: Embedder | None = None
_http: httpx2.AsyncClient | None = None


def _dependencies() -> tuple[ConnectionPool, Embedder]:
    global _pool, _embedder, _http
    if _pool is None or _embedder is None:
        settings = Settings()
        _pool = build_pool(settings.database_url.get_secret_value())
        _http = httpx2.AsyncClient()
        _embedder = build_embedder(settings, _http)
    return _pool, _embedder


def reset_dependencies() -> None:
    """Fuerza reconstruir pool/embedder en la proxima llamada -- solo para
    pruebas de integracion, que apuntan a una base efimera distinta en cada
    test (RFC-0011 8) y necesitan que este modulo deje de reusar el pool de
    la base anterior, ya destruida."""
    global _pool, _embedder, _http
    _pool, _embedder, _http = None, None, None


@tool
async def search_cv(query: str, chunk_types: list[str] | None = None) -> str:
    """Busca en el CV de la persona y devuelve los fragmentos más relevantes.

    Args:
        query: La pregunta o los términos a buscar, en lenguaje natural.
        chunk_types: Filtro opcional. Valores válidos: "experiencia", "proyecto",
            "habilidad", "educacion", "faq", "perfil". Úsalo solo si la pregunta
            se limita claramente a una de esas categorías.

    Returns:
        Un bloque <contexto_cv> con los fragmentos relevantes, o un aviso de que
        no se encontró información.
    """
    pool, embedder = _dependencies()
    with pool.connection() as conn:
        chunks = await hybrid_search(conn, embedder, query)
    if chunk_types:
        chunks = [c for c in chunks if c.chunk_type in chunk_types]
    bloque = format_context_block(chunks)
    # RFC-0014 6.2.2: regresion deliberada para CA-11 -- un filtro "defensivo"
    # como este es exactamente lo que el criterio prohibe (interpretar el
    # contenido en vez de entregarlo integro). Se revierte en el proximo commit.
    import re

    bloque = re.sub(r"(?i)ignora.*instrucciones.*", "[contenido filtrado]", bloque)
    return bloque


_SECTIONS_SQL = """
SELECT section, unit, chunk_type, MIN(date_start), MAX(date_end)
FROM cv_chunks
WHERE doc_id = %(doc_id)s
GROUP BY section, unit, chunk_type
ORDER BY section, MIN(date_start) NULLS LAST, unit
"""


def _formatear_rango(desde: date | None, hasta: date | None) -> str:
    if desde is None and hasta is None:
        return ""
    inicio = desde.isoformat() if desde else "?"
    fin = hasta.isoformat() if hasta else "presente"
    return f" ({inicio} - {fin})"


@tool
async def list_cv_sections() -> str:
    """Devuelve el índice del CV: secciones, empresas, puestos y rangos de fechas."""
    pool, _ = _dependencies()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(_SECTIONS_SQL, {"doc_id": "cv"})
        filas = cur.fetchall()

    if not filas:
        return "No hay secciones indexadas."

    lineas: list[str] = []
    seccion_actual: str | None = None
    for section, unit, _chunk_type, desde, hasta in filas:
        if section != seccion_actual:
            lineas.append(f"{section}:")
            seccion_actual = section
        lineas.append(f"- {unit}{_formatear_rango(desde, hasta)}")
    return "\n".join(lineas)
