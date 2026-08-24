"""RFC-0005 7, CA-7: cuerpo > 8 KB => 413 ANTES de tocar el agente.

El "antes" es el criterio, no un detalle: una entrada larga es la forma mas
barata de inflar el costo de tokens. Si el tope se comprobara despues de
invocar al agente, el 413 llegaria con el dinero ya gastado.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import enforce_body_limit
from app.api.errors import install_error_handling

pytestmark = pytest.mark.unit

_TOPE = 8 * 1024


@pytest.fixture
def cliente() -> tuple[TestClient, list[str]]:
    """Devuelve el cliente y la lista de invocaciones al 'agente', para poder
    afirmar que un cuerpo demasiado grande no llega nunca a el."""
    invocaciones: list[str] = []
    app = FastAPI()
    install_error_handling(app)

    @app.post("/v1/protegida", dependencies=[Depends(enforce_body_limit)])
    async def protegida(payload: dict[str, str]) -> dict[str, str]:
        invocaciones.append(payload.get("message", ""))
        return {"status": "ok"}

    return TestClient(app, raise_server_exceptions=False), invocaciones


def test_payload_too_large(cliente: tuple[TestClient, list[str]]) -> None:
    """CA-7: por encima del tope, 413 con el codigo de RFC-0005 8."""
    test_client, _ = cliente
    respuesta = test_client.post("/v1/protegida", json={"message": "x" * (_TOPE + 1)})

    assert respuesta.status_code == 413
    assert respuesta.json()["error"]["code"] == "payload_too_large"


def test_oversized_body_never_reaches_the_handler(cliente: tuple[TestClient, list[str]]) -> None:
    """CA-7, la parte que importa: el 413 ocurre ANTES del handler, asi que
    el agente -- y su gasto -- no se invoca."""
    test_client, invocaciones = cliente
    test_client.post("/v1/protegida", json={"message": "x" * (_TOPE + 1)})

    assert invocaciones == []


def test_body_within_the_limit_passes(cliente: tuple[TestClient, list[str]]) -> None:
    test_client, invocaciones = cliente
    respuesta = test_client.post("/v1/protegida", json={"message": "hola"})

    assert respuesta.status_code == 200
    assert invocaciones == ["hola"]
