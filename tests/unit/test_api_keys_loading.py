"""RFC-0005 10, CA-25: el proceso no arranca sin claves usables.

Sin claves no hay autenticacion posible, y arrancar sin ella deja la API
abierta. Una API cuyo unico efecto posible es `401` tampoco esta lista: se
trata igual que no tener claves.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import ApiKeysConfigError, load_api_keys

pytestmark = pytest.mark.unit

_CLAVE = "rcv_test_8sK2mNpQrStUvWxYz012"


def _documento(**overrides: object) -> str:
    entrada: dict[str, object] = {
        "id": "k_recruiter_01",
        "hash": hashlib.sha256(_CLAVE.encode()).hexdigest(),
        "role": "read",
        "label": "Reclutador",
        "expires_at": None,
        "active": True,
    }
    entrada.update(overrides)
    return json.dumps({"keys": [entrada]})


@pytest.mark.parametrize(
    ("raw", "motivo"),
    [
        (None, "ausente"),
        ("", "vacio"),
        ("   ", "solo espacios"),
        ("{no es json", "JSON invalido"),
        ('{"keys": []}', "sin ninguna clave"),
        ('{"otra_cosa": []}', "sin la clave 'keys'"),
    ],
)
def test_unusable_config_stops_the_process(raw: str | None, motivo: str) -> None:
    """CA-25: `API_KEYS_JSON` inutilizable => ApiKeysConfigError."""
    with pytest.raises(ApiKeysConfigError):
        load_api_keys(raw)


def test_every_key_inactive_stops_the_process() -> None:
    """CA-25: una API cuyo unico efecto posible es 401 no esta lista."""
    with pytest.raises(ApiKeysConfigError):
        load_api_keys(_documento(active=False))


def test_every_key_expired_stops_the_process() -> None:
    ayer = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with pytest.raises(ApiKeysConfigError):
        load_api_keys(_documento(expires_at=ayer))


def test_usable_config_loads_the_declared_keys() -> None:
    """El reverso de CA-25: si rechazara tambien lo valido, las pruebas de
    arriba pasarian sin que la condicion existiera."""
    manana = (datetime.now(UTC) + timedelta(days=30)).isoformat()

    claves = load_api_keys(_documento(expires_at=manana))

    assert len(claves) == 1
    assert claves[0].id == "k_recruiter_01"
    assert claves[0].role == "read"
    assert claves[0].expires_at is not None


def test_one_usable_key_is_enough() -> None:
    """Una revocada junto a una activa no impide arrancar: lo que CA-25
    exige es que quede al menos una utilizable."""
    activa = json.loads(_documento())["keys"][0]
    revocada = {**activa, "id": "k_revocada", "active": False}
    documento = json.dumps({"keys": [revocada, activa]})

    claves = load_api_keys(documento)

    assert len(claves) == 2
