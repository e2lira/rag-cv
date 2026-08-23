"""RFC-0011 CA-5: python -m app.dev_server arranca y /readyz responde 200 en
Windows, con el esqueleto minimo (sin base de datos ni logica de negocio)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

pytestmark = pytest.mark.unit


def test_readyz_returns_200() -> None:
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 200
