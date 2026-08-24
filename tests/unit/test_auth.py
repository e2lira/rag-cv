"""RFC-0005 6.2, CA-1 y CA-2: el 401 es siempre el mismo 401.

CA-1: sin `X-API-Key` => 401 con cuerpo generico.
CA-2: clave revocada y clave inexistente devuelven respuestas identicas.

La segunda es la que importa de verdad: si difieren en una coma, un atacante
tiene un oraculo que le dice cuales de sus claves existieron alguna vez.

Sin base de datos: la verificacion es logica pura sobre el documento de
claves (RFC-0005 6.1). El limite de tasa, que si toca PostgreSQL, va en su
propia prueba de integracion.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import require_role
from app.api.errors import REQUEST_ID_HEADER, install_error_handling
from app.core.security import ApiKey, load_api_keys

pytestmark = pytest.mark.unit

_ACTIVA = "rcv_test_activaAAAAAAAAAAAAAAAA"
_REVOCADA = "rcv_test_revocadaRRRRRRRRRRRRRRR"
_EXPIRADA = "rcv_test_expiradaEEEEEEEEEEEEEEE"
_INEXISTENTE = "rcv_test_inexistenteIIIIIIIIIIII"


def _hash(clave: str) -> str:
    return hashlib.sha256(clave.encode()).hexdigest()


def _claves() -> tuple[ApiKey, ...]:
    ayer = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    documento = {
        "keys": [
            {
                "id": "k_activa",
                "hash": _hash(_ACTIVA),
                "role": "read",
                "label": "Activa",
                "expires_at": None,
                "active": True,
            },
            {
                "id": "k_revocada",
                "hash": _hash(_REVOCADA),
                "role": "read",
                "label": "Revocada",
                "expires_at": None,
                "active": False,
            },
            {
                "id": "k_expirada",
                "hash": _hash(_EXPIRADA),
                "role": "read",
                "label": "Expirada",
                "expires_at": ayer,
                "active": True,
            },
        ]
    }
    return load_api_keys(json.dumps(documento))


@pytest.fixture
def cliente() -> TestClient:
    app = FastAPI()
    install_error_handling(app)
    app.state.api_keys = _claves()

    @app.get("/v1/protegida", dependencies=[Depends(require_role("read"))])
    async def protegida() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app, raise_server_exceptions=False)


def test_missing_key(cliente: TestClient) -> None:
    """CA-1: sin cabecera => 401 con el cuerpo de RFC-0005 8."""
    respuesta = cliente.get("/v1/protegida")

    assert respuesta.status_code == 401
    error = respuesta.json()["error"]
    assert error["code"] == "unauthorized"
    assert error["request_id"]


def test_valid_key_passes(cliente: TestClient) -> None:
    respuesta = cliente.get("/v1/protegida", headers={"X-API-Key": _ACTIVA})

    assert respuesta.status_code == 200


def test_bearer_header_is_accepted(cliente: TestClient) -> None:
    """RFC-0005 6.2: `Authorization: Bearer` tambien autentica -- es lo que
    usa la plataforma de Open Responses (13.1)."""
    respuesta = cliente.get("/v1/protegida", headers={"Authorization": f"Bearer {_ACTIVA}"})

    assert respuesta.status_code == 200


def _sin_correlacion(respuesta: object) -> dict[str, object]:
    """El `request_id` cambia en cada peticion por diseno (CA-12): compararlo
    haria fallar CA-2 por la razon equivocada."""
    cuerpo = respuesta.json()  # type: ignore[attr-defined]
    cuerpo["error"].pop("request_id")
    return cuerpo


@pytest.mark.parametrize("clave", [_REVOCADA, _EXPIRADA, _INEXISTENTE])
def test_no_oracle(cliente: TestClient, clave: str) -> None:
    """CA-2: revocada, expirada e inexistente son la MISMA respuesta.

    Se comparan estado, cuerpo y cabeceras (salvo la de correlacion): una
    diferencia en cualquiera de los tres es el oraculo que 6.2 prohibe."""
    referencia = cliente.get("/v1/protegida", headers={"X-API-Key": _INEXISTENTE})
    otra = cliente.get("/v1/protegida", headers={"X-API-Key": clave})

    assert otra.status_code == referencia.status_code == 401
    assert _sin_correlacion(otra) == _sin_correlacion(referencia)

    cabeceras_otra = {k: v for k, v in otra.headers.items() if k != REQUEST_ID_HEADER.lower()}
    cabeceras_ref = {k: v for k, v in referencia.headers.items() if k != REQUEST_ID_HEADER.lower()}
    assert cabeceras_otra == cabeceras_ref


def test_missing_key_is_indistinguishable_from_a_wrong_one(cliente: TestClient) -> None:
    """CA-1 + CA-2 juntas: tampoco se distingue 'no mandaste clave' de
    'mandaste una que no vale'."""
    sin_clave = cliente.get("/v1/protegida")
    con_clave_mala = cliente.get("/v1/protegida", headers={"X-API-Key": _INEXISTENTE})

    assert _sin_correlacion(sin_clave) == _sin_correlacion(con_clave_mala)


def test_insufficient_role_is_403_not_401(cliente: TestClient) -> None:
    """RFC-0005 6.3 y 8: rol insuficiente es 403, no 401. Aqui si se
    distingue, y debe: la clave es valida y su dueno tiene derecho a saber
    que el problema es el permiso, no la credencial."""
    app = FastAPI()
    install_error_handling(app)
    app.state.api_keys = _claves()

    @app.get("/v1/admin/algo", dependencies=[Depends(require_role("admin"))])
    async def solo_admin() -> dict[str, str]:
        return {"status": "ok"}

    respuesta = TestClient(app, raise_server_exceptions=False).get(
        "/v1/admin/algo", headers={"X-API-Key": _ACTIVA}
    )

    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "forbidden"
