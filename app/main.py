"""Punto de entrada de la aplicacion.

La aplicacion real -- RFC-0021: el lifespan valida el arranque, y si algo
esta mal no arranca. app/dev_server.py es el lanzador de DEV que fija la
politica del bucle de eventos antes de arrancar esto (RFC-0011 #5.1).
RFC-0005 amplia /readyz con su contrato real.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI

from app.core.engine import build_pool
from app.core.migrations import resolve_expected_head
from app.core.platform import assert_compatible_loop
from app.core.settings import Settings
from app.core.startup_checks import (
    check_alembic_head,
    check_embedding_dimension,
    check_extensions_present,
    check_pgvector_version,
    check_single_embed_model,
)
from app.retrieval.embedder import build_embedder


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Paso 0, y va primero (RFC-0021 5): unica defensa de RFC-0011 CA-4
    # dentro de este RFC. Si esto se moviera despues del pool, el CLI de
    # uvicorn en Windows fallaria por la base y no por el bucle.
    assert_compatible_loop()

    settings = Settings()

    async with httpx2.AsyncClient() as http:
        # No gasta dinero: la fabrica instancia, no llama a la API
        # (ADR-0012). Si construye lo antes posible, para no esperar a la
        # primera consulta si EMBEDDER nombra una implementacion diferida
        # (RFC-0021 6).
        embedder = build_embedder(settings, http)

    pool = build_pool(settings.database_url)
    try:
        with pool.connection() as conn:
            check_extensions_present(conn)
            check_pgvector_version(conn)
            check_alembic_head(conn, resolve_expected_head())
            check_embedding_dimension(conn, settings.embedding_dim)
            check_single_embed_model(conn, embedder.model_id)

        yield
    finally:
        pool.close()


app = FastAPI(lifespan=lifespan)


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ok"}
