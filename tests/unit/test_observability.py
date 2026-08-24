"""RFC-0005 8, CA-12: `X-Request-ID` en la respuesta y en los logs del turno.

Es el unico identificador que se le pide a un usuario para investigar un
incidente: si no aparece en las dos partes, no sirve para correlacionar.

La captura de logs usa un handler propio, no `caplog`: en este repositorio
`caplog` ya demostro no ser reproducible con la suite completa (PR #73, el
par de CA-8/CA-9 de RFC-0013). Un handler adjuntado y retirado por el propio
test no depende del estado de logging compartido.
"""

import logging

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.errors import REQUEST_ID_HEADER, current_request_id, install_error_handling

pytestmark = pytest.mark.unit

_LOGGER = "app.api.prueba"


class _Capturador(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.registros: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.registros.append(record)


@pytest.fixture
def cliente() -> TestClient:
    app = FastAPI()
    install_error_handling(app)
    logger = logging.getLogger(_LOGGER)

    @app.get("/ok")
    async def ok(request: Request) -> dict[str, str]:
        logger.info("turno atendido", extra={"request_id": current_request_id(request)})
        return {"status": "ok"}

    @app.get("/revienta")
    async def revienta() -> dict[str, str]:
        raise RuntimeError("fallo cualquiera")

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def capturador() -> _Capturador:
    handler = _Capturador()
    logger = logging.getLogger(_LOGGER)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


def test_request_id_header_present_on_success(cliente: TestClient) -> None:
    """CA-12: la cabecera viaja tambien cuando todo sale bien."""
    assert cliente.get("/ok").headers[REQUEST_ID_HEADER]


def test_request_id_header_present_on_error(cliente: TestClient) -> None:
    assert cliente.get("/revienta").headers[REQUEST_ID_HEADER]


def test_request_id_matches_the_error_body(cliente: TestClient) -> None:
    """CA-12: el de la cabecera y el del cuerpo son el mismo. Si difieren, el
    usuario reporta uno y en los logs esta el otro."""
    respuesta = cliente.get("/revienta")

    assert respuesta.headers[REQUEST_ID_HEADER] == respuesta.json()["error"]["request_id"]


def test_request_id_is_unique_per_request(cliente: TestClient) -> None:
    """Sin esto, correlacionar es imposible: dos incidentes distintos
    compartirian identificador."""
    primero = cliente.get("/ok").headers[REQUEST_ID_HEADER]
    segundo = cliente.get("/ok").headers[REQUEST_ID_HEADER]

    assert primero != segundo


def test_request_id_reaches_the_logs(cliente: TestClient, capturador: _Capturador) -> None:
    """CA-12: el mismo identificador aparece en el log del turno."""
    respuesta = cliente.get("/ok")

    (registro,) = capturador.registros
    assert registro.request_id == respuesta.headers[REQUEST_ID_HEADER]
