"""RFC-0005 8, CA-9: un 500 no expone traza, SQL ni recursos internos.

Invariante I-6. El unico dato que sale es el `request_id`, que es lo que se
le pide al usuario para investigar el incidente.

La app de prueba se ensambla con los componentes REALES de `app/api/` y una
ruta que revienta a proposito: se prueba el manejo de errores, no un doble
de el (P-2).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.errors import install_error_handling

pytestmark = pytest.mark.unit

_SECRETO_EN_LA_TRAZA = "SELECT hash FROM api_keys WHERE id = 'k_recruiter_01'"


@pytest.fixture
def cliente() -> TestClient:
    app = FastAPI()
    install_error_handling(app)

    @app.get("/revienta")
    async def revienta() -> dict[str, str]:
        raise RuntimeError(_SECRETO_EN_LA_TRAZA)

    # raise_server_exceptions=False: sin esto TestClient relanza la excepcion
    # en el test en vez de dejar que la app la convierta en respuesta, y no
    # se estaria probando el manejador.
    return TestClient(app, raise_server_exceptions=False)


def test_no_internal_leak(cliente: TestClient) -> None:
    """CA-9: ni el texto de la excepcion, ni SQL, ni el nombre del modulo."""
    respuesta = cliente.get("/revienta")

    assert respuesta.status_code == 500
    cuerpo = respuesta.text
    assert _SECRETO_EN_LA_TRAZA not in cuerpo
    assert "SELECT" not in cuerpo
    assert "RuntimeError" not in cuerpo
    assert "Traceback" not in cuerpo
    assert "test_errors" not in cuerpo


def test_500_uses_the_contract_shape(cliente: TestClient) -> None:
    """RFC-0005 8: el cuerpo es {"error": {code, message, request_id}}."""
    respuesta = cliente.get("/revienta")

    error = respuesta.json()["error"]
    assert error["code"] == "internal_error"
    assert error["message"]
    assert error["request_id"]


def test_invalid_schema_is_400_with_the_contract_shape() -> None:
    """RFC-0005 8: un esquema invalido es `400 invalid_request` con el sobre
    unico. FastAPI devuelve por defecto `422` con `{"detail": [...]}`, que no
    esta en la tabla de 8 y rompe a cualquier cliente que lea el contrato."""
    app = FastAPI()
    install_error_handling(app)

    class Cuerpo(BaseModel):
        message: str

    @app.post("/v1/eco")
    async def eco(payload: Cuerpo) -> dict[str, str]:
        return {"message": payload.message}

    cliente = TestClient(app, raise_server_exceptions=False)

    respuesta = cliente.post("/v1/eco", json={"mensaje_mal_escrito": "hola"})

    assert respuesta.status_code == 400
    error = respuesta.json()["error"]
    assert error["code"] == "invalid_request"
    assert error["request_id"]


def test_invalid_schema_does_not_leak_the_internal_detail() -> None:
    """El 422 de FastAPI publica la ruta del campo y el tipo esperado. Es
    util depurando y es superficie de mas en produccion: I-6 dice que el
    cuerpo de error no lleva nombres de recursos internos."""
    app = FastAPI()
    install_error_handling(app)

    class Cuerpo(BaseModel):
        message: str

    @app.post("/v1/eco")
    async def eco(payload: Cuerpo) -> dict[str, str]:
        return {"message": payload.message}

    respuesta = TestClient(app, raise_server_exceptions=False).post("/v1/eco", json={})

    cuerpo = respuesta.text
    assert "detail" not in respuesta.json()
    assert "body" not in cuerpo
    assert "missing" not in cuerpo


def test_404_also_uses_the_contract_shape(cliente: TestClient) -> None:
    """RFC-0005 8: el formato es de toda respuesta de error, no solo del 500.
    Una ruta inexistente la sirve Starlette, no nuestro codigo: sin manejador
    propio devolveria {"detail": "Not Found"}, que no es el contrato."""
    respuesta = cliente.get("/no-existe")

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "not_found"
