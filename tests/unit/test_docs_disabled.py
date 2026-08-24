"""RFC-0005 9, CA-10: `/docs` y `/openapi.json` solo si `APP_ENV != "prod"`.

La documentacion interactiva publica el contrato entero: rutas, esquemas y
cabeceras de autenticacion. En DEV y QA eso es util; en PROD es un mapa
gratis de la superficie de ataque.
"""

import pytest
from fastapi.testclient import TestClient

from app.api.app_factory import create_app

pytestmark = pytest.mark.unit


def _cliente(app_env: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.setenv("PROVEEDOR", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.mark.parametrize("ruta", ["/docs", "/openapi.json", "/redoc"])
def test_docs_disabled_in_prod(ruta: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """CA-10: con `APP_ENV=prod` las tres rutas devuelven 404."""
    respuesta = _cliente("prod", monkeypatch).get(ruta)

    assert respuesta.status_code == 404


@pytest.mark.parametrize("app_env", ["dev", "qa"])
@pytest.mark.parametrize("ruta", ["/docs", "/openapi.json"])
def test_docs_available_outside_prod(
    app_env: str, ruta: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El reverso de CA-10: si tambien estuvieran apagadas fuera de PROD, la
    prueba de arriba pasaria sin que la condicion existiera."""
    respuesta = _cliente(app_env, monkeypatch).get(ruta)

    assert respuesta.status_code == 200


def test_docs_404_uses_the_error_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0005 8: el 404 de PROD es un 404 normal del contrato, no una
    pagina de FastAPI que revele que la ruta existe pero esta apagada."""
    respuesta = _cliente("prod", monkeypatch).get("/docs")

    assert respuesta.json()["error"]["code"] == "not_found"
