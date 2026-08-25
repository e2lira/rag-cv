"""Punto de entrada de la aplicacion.

La aplicacion real -- RFC-0021: el lifespan valida el arranque, y si algo
esta mal no arranca. app/dev_server.py es el lanzador de DEV que fija la
politica del bucle de eventos antes de arrancar esto (RFC-0011 #5.1).

El router, el manejo de errores y la politica de /docs los arma
`app/api/app_factory.py` (RFC-0005 9); aqui queda el arranque validado y el
estado que las dependencias de `/v1/*` leen (claves, cuotas, pool).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from fastapi import FastAPI

from app.agent.builder import AgentFactory
from app.api.app_factory import create_app
from app.core.engine import build_pool
from app.core.migrations import resolve_expected_head
from app.core.platform import assert_compatible_loop
from app.core.security import load_api_keys
from app.core.settings import Settings
from app.core.startup_checks import (
    check_alembic_head,
    check_embedding_dimension,
    check_extensions_present,
    check_pgvector_version,
    check_single_embed_model,
)
from app.ingestion.corpus_parser import parse_front_matter
from app.retrieval.embedder import build_embedder


def _persona(settings: Settings) -> str:
    """El nombre del que habla el prompt, leido del corpus (RFC-0004 4).

    Del front-matter y no de una constante: el prompt de sistema es uno solo
    y se parametriza, asi que cambiar de CV no debe exigir tocar codigo. Si
    el corpus no lo declara, el arranque falla aqui -- un agente que dice
    "Eres el agente de CV de " no sirve para nada, y fallar al arrancar es
    mas barato que descubrirlo en la primera pregunta (RFC-0021).
    """
    frontal = parse_front_matter(settings.corpus_path.read_text(encoding="utf-8"))
    persona = str(frontal.get("persona", "")).strip()
    if not persona:
        raise RuntimeError(f"El corpus {settings.corpus_path} no declara `persona` (RFC-0004 4)")
    return persona


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Paso 0, y va primero (RFC-0021 5): unica defensa de RFC-0011 CA-4
    # dentro de este RFC. Si esto se moviera despues del pool, el CLI de
    # uvicorn en Windows fallaria por la base y no por el bucle.
    assert_compatible_loop()

    settings = Settings()

    # Antes que el pool: sin claves utilizables el proceso no arranca
    # (RFC-0005 10, CA-25), y no tiene sentido abrir conexiones para una
    # API que no podria autenticar a nadie.
    app.state.api_keys = load_api_keys(settings.api_keys_json)
    app.state.rate_limit_per_minute = settings.rate_limit_per_minute
    app.state.rate_limit_per_day = settings.rate_limit_per_day

    async with httpx2.AsyncClient() as http:
        # No gasta dinero: la fabrica instancia, no llama a la API
        # (ADR-0012). Si construye lo antes posible, para no esperar a la
        # primera consulta si EMBEDDER nombra una implementacion diferida
        # (RFC-0021 6).
        embedder = build_embedder(settings, http)

    # Lo que se construye una vez por proceso es el MODELO, no el agente
    # (ADR-0017): `build_model` resuelve credenciales y cliente del
    # proveedor, y eso no conviene repetirlo. El agente lo arma la fabrica
    # por turno, porque el objeto `Agent` de strands acumula `self.messages`
    # y uno de vida larga concatenaria las conversaciones de todos los
    # usuarios -- la fuga que RFC-0004 6 decia evitar y producia.
    app.state.agent_factory = AgentFactory.from_settings(settings, _persona(settings))

    pool = build_pool(settings.database_url.get_secret_value())
    app.state.db_pool = pool
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


app = create_app(lifespan=lifespan)
