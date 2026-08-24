"""RFC-0005 8, CA-12: `X-Request-ID` en la respuesta y en **todas** las
lineas de log del turno.

Es el unico identificador que se le pide a un usuario para investigar un
incidente: si una sola linea del turno sale sin el, la correlacion se rompe
justo cuando hace falta.

Por eso lo que se prueba es que la correlacion sea **automatica**. Un test
que pasara `extra={"request_id": ...}` a mano probaria que el test sabe
pasarlo, no que el sistema lo ponga: cualquier logger de produccion que se
olvidara del `extra` quedaria sin correlacionar y la prueba seguiria verde.

La captura usa un handler propio, no `caplog`: en este repositorio `caplog`
ya demostro no ser reproducible con la suite completa (PR #73, el par de
CA-8/CA-9 de RFC-0013).
"""

import logging

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.errors import REQUEST_ID_HEADER, install_error_handling

pytestmark = pytest.mark.unit

# Un logger cualquiera de la aplicacion, que NO sabe nada de request_id.
_LOGGER = "app.dominio.cualquiera"


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
        # Sin `extra`: es el punto. Un logger corriente no deberia tener que
        # saber que existe un request_id para que sus lineas lo lleven.
        logger.info("primera linea del turno")
        logger.info("segunda linea del turno")
        return {"status": "ok"}

    @app.get("/revienta")
    async def revienta() -> dict[str, str]:
        raise RuntimeError("fallo cualquiera")

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def capturador():  # noqa: ANN201 -- generador de pytest
    handler = _Capturador()
    logger = logging.getLogger(_LOGGER)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


def test_request_id_header_present_on_success(cliente: TestClient) -> None:
    assert cliente.get("/ok").headers[REQUEST_ID_HEADER]


def test_request_id_header_present_on_error(cliente: TestClient) -> None:
    assert cliente.get("/revienta").headers[REQUEST_ID_HEADER]


def test_request_id_matches_the_error_body(cliente: TestClient) -> None:
    """CA-12: el de la cabecera y el del cuerpo son el mismo. Si difieren, el
    usuario reporta uno y en los logs esta el otro."""
    respuesta = cliente.get("/revienta")

    assert respuesta.headers[REQUEST_ID_HEADER] == respuesta.json()["error"]["request_id"]


def test_request_id_is_unique_per_request(cliente: TestClient) -> None:
    primero = cliente.get("/ok").headers[REQUEST_ID_HEADER]
    segundo = cliente.get("/ok").headers[REQUEST_ID_HEADER]

    assert primero != segundo


def test_every_log_line_carries_the_request_id(
    cliente: TestClient, capturador: _Capturador
) -> None:
    """CA-12, el criterio real: **todas** las lineas, sin que el logger haga
    nada. Con dos lineas basta para distinguir "se correlaciona" de "el test
    correlaciono una"."""
    respuesta = cliente.get("/ok")

    esperado = respuesta.headers[REQUEST_ID_HEADER]
    assert len(capturador.registros) == 2
    assert [getattr(r, "request_id", None) for r in capturador.registros] == [esperado, esperado]


def test_two_requests_do_not_share_the_identifier(
    cliente: TestClient, capturador: _Capturador
) -> None:
    """Si el contexto se filtrara entre peticiones, correlacionar seria peor
    que no tener nada: apuntaria al incidente equivocado."""
    primera = cliente.get("/ok").headers[REQUEST_ID_HEADER]
    segunda = cliente.get("/ok").headers[REQUEST_ID_HEADER]

    identificadores = [getattr(r, "request_id", None) for r in capturador.registros]
    assert identificadores == [primera, primera, segunda, segunda]


def test_a_log_outside_any_request_still_formats(capturador: _Capturador) -> None:
    """Un log fuera de una peticion (arranque, cron) no debe reventar por
    falta de contexto: lleva el campo vacio, no ausente. Un formateador que
    espere `%(request_id)s` fallaria con un `KeyError` si el atributo no
    existiera, y un fallo de logging tumbaria el arranque."""
    logging.getLogger(_LOGGER).info("linea de arranque")

    (registro,) = capturador.registros
    assert getattr(registro, "request_id", None) == ""
