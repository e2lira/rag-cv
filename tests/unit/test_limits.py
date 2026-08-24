"""RFC-0005 7, CA-7: cuerpo > 8 KB => 413 ANTES de tocar el agente.

El "antes" es el criterio, no un detalle: una entrada larga es la forma mas
barata de inflar el costo de tokens. Si el tope se comprobara despues de
invocar al agente, el 413 llegaria con el dinero ya gastado.
"""

import json
from collections.abc import Iterator

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


def _troceado(payload: bytes) -> Iterator[bytes]:
    """Generador: httpx lo envia con `Transfer-Encoding: chunked`, **sin**
    `Content-Length`. Es la forma normal de subir algo cuyo tamano no se
    conoce por adelantado, y cualquier cliente puede usarla."""
    for i in range(0, len(payload), 1024):
        yield payload[i : i + 1024]


def test_payload_too_large_without_content_length(cliente: tuple[TestClient, list[str]]) -> None:
    """CA-7: el tope tambien se aplica cuando no hay `Content-Length`.

    Mirar solo la cabecera declarada deja el limite a merced del cliente:
    quien quiera saltarselo solo tiene que no declararla."""
    test_client, _ = cliente
    grande = json.dumps({"message": "x" * (_TOPE + 1)}).encode()

    respuesta = test_client.post(
        "/v1/protegida",
        content=_troceado(grande),
        headers={"Content-Type": "application/json"},
    )

    assert respuesta.status_code == 413
    assert respuesta.json()["error"]["code"] == "payload_too_large"


def test_oversized_chunked_body_never_reaches_the_handler(
    cliente: tuple[TestClient, list[str]],
) -> None:
    """CA-7, la parte que importa: sin `Content-Length` tampoco llega al
    handler, asi que el agente -- y su gasto -- no se invoca."""
    test_client, invocaciones = cliente
    grande = json.dumps({"message": "x" * (_TOPE + 1)}).encode()

    test_client.post(
        "/v1/protegida",
        content=_troceado(grande),
        headers={"Content-Type": "application/json"},
    )

    assert invocaciones == []


def test_chunked_body_within_the_limit_still_passes(
    cliente: tuple[TestClient, list[str]],
) -> None:
    """El reverso: contar mientras se lee no debe romper una peticion
    legitima que llegue troceada."""
    test_client, invocaciones = cliente
    pequeno = json.dumps({"message": "hola"}).encode()

    respuesta = test_client.post(
        "/v1/protegida",
        content=_troceado(pequeno),
        headers={"Content-Type": "application/json"},
    )

    assert respuesta.status_code == 200
    assert invocaciones == ["hola"]
