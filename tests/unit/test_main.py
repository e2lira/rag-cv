"""RFC-0011 CA-5: python -m app.dev_server arranca y /readyz responde 200 en
Windows, con el esqueleto minimo (sin base de datos ni logica de negocio)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.unit


def test_readyz_returns_200() -> None:
    # TestClient(app) sin "with" no ejecuta el lifespan a proposito: pytest
    # en Windows arranca su propio ProactorEventLoop (no pasa por
    # app/dev_server.py, que es quien fija la politica antes de crear
    # cualquier bucle), asi que ejercitar el lifespan real aqui haria que
    # assert_compatible_loop() rechace el bucle de PYTEST, no el de la
    # aplicacion -- exactamente lo que RFC-0011 #5.1 dice que debe pasar
    # fuera de dev_server.py. Esa comprobacion ya la cubre
    # test_platform.py::test_proactor_detected de forma aislada; aqui solo
    # se prueba la ruta. El lifespan real se verifico con humo (CA-5).
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 200
