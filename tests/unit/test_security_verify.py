"""RFC-0005 6.2, CA-4: la verificacion es de tiempo constante.

Y todos los fallos son el mismo fallo: no se distingue inexistente de
revocada o expirada. Distinguirlos es un oraculo para un atacante.

El 401 que envuelve este `None` es del router (`app/api/deps.py`); aqui se
prueba la decision, no como se comunica.
"""

import hashlib
import inspect
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core import security
from app.core.security import ApiKey, load_api_keys, verify_api_key

pytestmark = pytest.mark.unit

_ACTIVA = "rcv_test_activaAAAAAAAAAAAAAAAA"
_INEXISTENTE = "rcv_test_inexistenteIIIIIIIIIIII"


def _hash(clave: str) -> str:
    return hashlib.sha256(clave.encode()).hexdigest()


def _entrada(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "k_activa",
        "hash": _hash(_ACTIVA),
        "role": "read",
        "label": "Activa",
        "expires_at": None,
        "active": True,
    }
    base.update(overrides)
    return base


def _claves(*entradas: dict[str, object]) -> tuple[ApiKey, ...]:
    return load_api_keys(json.dumps({"keys": list(entradas) or [_entrada()]}))


def test_constant_time_compare() -> None:
    """CA-4: la comparacion usa `hmac.compare_digest`, no `==`.

    Se comprueba por inspeccion porque es lo que prescribe el propio RFC:
    medir tiempos produciria una prueba intermitente (P-7, P-10), que es
    peor que ninguna porque acaba desactivada."""
    fuente = inspect.getsource(security.verify_api_key)

    assert "compare_digest" in fuente
    assert "==" not in fuente.replace("!=", "")


def test_the_right_key_is_found() -> None:
    encontrada = verify_api_key(_ACTIVA, _claves())

    assert encontrada is not None
    assert encontrada.id == "k_activa"


@pytest.mark.parametrize(
    ("presentada", "motivo"),
    [(None, "cabecera ausente"), ("", "cabecera vacia"), (_INEXISTENTE, "clave inexistente")],
)
def test_rejects(presentada: str | None, motivo: str) -> None:
    assert verify_api_key(presentada, _claves()) is None


def test_a_revoked_key_is_rejected() -> None:
    """RFC-0005 6.2: `active: false` no autentica. Sin esta comprobacion,
    revocar una clave no surtiria ningun efecto."""
    revocada = _claves(_entrada(active=False, id="k_revocada"))

    assert verify_api_key(_ACTIVA, revocada) is None


def test_an_expired_key_is_rejected() -> None:
    ayer = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    expirada = _claves(_entrada(expires_at=ayer, id="k_expirada"))

    assert verify_api_key(_ACTIVA, expirada) is None


def test_all_rejections_are_the_same_value() -> None:
    """CA-2 a nivel de modulo: revocada, expirada e inexistente devuelven
    exactamente lo mismo. Si una devolviera algo distinto de `None`, el
    router podria filtrar la diferencia al cliente."""
    ayer = (datetime.now(UTC) - timedelta(days=1)).isoformat()

    resultados = [
        verify_api_key(_INEXISTENTE, _claves()),
        verify_api_key(_ACTIVA, _claves(_entrada(active=False, id="k_revocada"))),
        verify_api_key(_ACTIVA, _claves(_entrada(expires_at=ayer, id="k_expirada"))),
    ]

    assert resultados == [None, None, None]


def test_a_key_present_later_in_the_list_is_still_found() -> None:
    """El recorrido no corta en la primera coincidencia (RFC-0005 6.2): si
    lo hiciera, el tiempo de respuesta filtraria la posicion en la lista, y
    eso reintroduce por el orden lo que `compare_digest` cierra por el
    contenido."""
    otra = _entrada(id="k_otra", hash=_hash("rcv_test_otraOOOOOOOOOOOOOOOOO"))
    claves = _claves(otra, _entrada())

    encontrada = verify_api_key(_ACTIVA, claves)

    assert encontrada is not None
    assert encontrada.id == "k_activa"
