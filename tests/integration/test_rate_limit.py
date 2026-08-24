"""RFC-0005 7, CA-6: superar la cuota devuelve 429 con `Retry-After` correcto.

Integracion porque el contador vive en PostgreSQL (`rate_buckets`,
RFC-0006 4.4): la atomicidad del `INSERT ... ON CONFLICT` es justo lo que un
doble no probaria.

La cuota se fija baja para no hacer 31 peticiones por prueba; los topes
reales (30/1000) son de la configuracion, no del contrato de la dependencia.
"""

import psycopg
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import rate_limiter
from app.api.errors import install_error_handling
from app.core.engine import build_pool

pytestmark = pytest.mark.integration


def _app(database_url: str, *, por_minuto: int, por_dia: int) -> TestClient:
    app = FastAPI()
    install_error_handling(app)
    # Pool y no una conexion por peticion: la cuota corre en CADA peticion,
    # y abrir un TCP mas autenticar cada vez se comeria el presupuesto de
    # latencia de RNF-2. `build_pool` existe justo para esto (RFC-0006 6).
    app.state.db_pool = build_pool(database_url, min_size=1, max_size=2)
    app.state.rate_limit_per_minute = por_minuto
    app.state.rate_limit_per_day = por_dia

    @app.get("/v1/consulta", dependencies=[Depends(rate_limiter("k_prueba"))])
    async def consulta() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app, raise_server_exceptions=False)


def test_within_quota_passes_and_publishes_the_headers(database_url: str) -> None:
    cliente = _app(database_url, por_minuto=3, por_dia=100)

    respuesta = cliente.get("/v1/consulta")

    assert respuesta.status_code == 200
    assert respuesta.headers["X-RateLimit-Limit"] == "3"
    assert respuesta.headers["X-RateLimit-Remaining"] == "2"
    assert respuesta.headers["X-RateLimit-Reset"].isdigit()


def test_exceeding_the_quota_returns_429_with_retry_after(database_url: str) -> None:
    """CA-6: el 429 llega con `Retry-After` y con el sobre de error de 8."""
    cliente = _app(database_url, por_minuto=2, por_dia=100)

    cliente.get("/v1/consulta")
    cliente.get("/v1/consulta")
    rechazada = cliente.get("/v1/consulta")

    assert rechazada.status_code == 429
    assert rechazada.json()["error"]["code"] == "rate_limited"
    # Dentro del minuto en curso: como mucho 60 s, y nunca 0 (ADR-0016).
    retry_after = int(rechazada.headers["Retry-After"])
    assert 1 <= retry_after <= 60
    assert rechazada.headers["X-RateLimit-Limit"] == "2"
    assert rechazada.headers["X-RateLimit-Remaining"] == "0"


def test_the_quota_is_per_key(database_url: str) -> None:
    """RFC-0005 7: la ventana es por `key_id`. Si fuera global, una clave
    agotaria la cuota de todas las demas."""
    app = FastAPI()
    install_error_handling(app)
    app.state.db_pool = build_pool(database_url, min_size=1, max_size=2)
    app.state.rate_limit_per_minute = 1
    app.state.rate_limit_per_day = 100

    @app.get("/v1/una", dependencies=[Depends(rate_limiter("k_una"))])
    async def una() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/otra", dependencies=[Depends(rate_limiter("k_otra"))])
    async def otra() -> dict[str, str]:
        return {"status": "ok"}

    cliente = TestClient(app, raise_server_exceptions=False)

    assert cliente.get("/v1/una").status_code == 200
    assert cliente.get("/v1/una").status_code == 429
    # La otra clave no quedo afectada por el gasto de la primera.
    assert cliente.get("/v1/otra").status_code == 200


def test_the_day_bucket_also_rejects(database_url: str) -> None:
    """Las dos cubetas se comprueban, no solo la de minuto."""
    cliente = _app(database_url, por_minuto=1000, por_dia=2)

    cliente.get("/v1/consulta")
    cliente.get("/v1/consulta")
    rechazada = cliente.get("/v1/consulta")

    assert rechazada.status_code == 429
    assert rechazada.headers["X-RateLimit-Limit"] == "2"
    # Cierra al final del dia UTC: mucho mas que un minuto.
    assert int(rechazada.headers["Retry-After"]) > 60


def test_both_buckets_are_incremented_every_request(database_url: str) -> None:
    """RFC-0005 7: "se incrementan las dos, siempre". Si solo se incrementara
    la que se consulta, la cubeta de dia nunca llegaria a su tope."""
    cliente = _app(database_url, por_minuto=100, por_dia=100)

    cliente.get("/v1/consulta")
    cliente.get("/v1/consulta")

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT window_kind, count FROM rate_buckets WHERE key_id = %s ORDER BY window_kind",
            ("k_prueba",),
        )
        filas = cur.fetchall()

    assert filas == [("day", 2), ("minute", 2)]
