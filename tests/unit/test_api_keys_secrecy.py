"""RFC-0005 6.1, CA-5: en el servidor solo vive `sha256(clave)`.

La invariante no es "el `repr` no la enseña" -- es que la clave en claro
**no llegue a estar** en memoria. Ocultarla en el `repr` no impide
guardarla; solo impide verla por una via.

Por eso la comprobacion fuerte es la primera: un `API_KEYS_JSON`
estructuralmente valido que ponga la clave en claro en `hash` tiene que
impedir el arranque, no aceptarse. Ademas de romper la invariante, esa
configuracion queda rota en silencio: `verify_api_key` compara
`sha256(presentada)` contra un valor que no es un hash, asi que la clave
legitima nunca autentica y el sintoma es un 401 inexplicable.
"""

import hashlib
import json

import pytest

from app.core.security import ApiKeysConfigError, load_api_keys

pytestmark = pytest.mark.unit

_CLAVE = "rcv_test_8sK2mNpQrStUvWxYz012"
_HASH = hashlib.sha256(_CLAVE.encode()).hexdigest()


def _documento(hash_value: str) -> str:
    return json.dumps(
        {
            "keys": [
                {
                    "id": "k_recruiter_01",
                    "hash": hash_value,
                    "role": "read",
                    "label": "Reclutador",
                    "expires_at": None,
                    "active": True,
                }
            ]
        }
    )


@pytest.mark.parametrize(
    ("valor", "motivo"),
    [
        (_CLAVE, "la clave en claro"),
        ("rcv_live_otraClaveEnClaro12345", "otra clave en claro"),
        ("no-es-un-hash", "texto arbitrario"),
        (_HASH[:-1], "63 caracteres, un digito corto"),
        (_HASH + "0", "65 caracteres"),
        (_HASH[:-1] + "z", "64 caracteres pero no hexadecimal"),
        ("", "vacio"),
    ],
)
def test_a_hash_that_is_not_sha256_stops_the_process(valor: str, motivo: str) -> None:
    """CA-5: el campo `hash` que no es un SHA-256 impide arrancar.

    Es la unica forma de garantizar que el servidor no retiene la clave: si
    se acepta cualquier cadena, un secreto mal escrito la deja en memoria."""
    with pytest.raises(ApiKeysConfigError):
        load_api_keys(_documento(valor))


def test_a_real_sha256_is_accepted() -> None:
    """El reverso: si rechazara tambien lo valido, la prueba de arriba
    pasaria sin que la validacion distinguiera nada."""
    (clave,) = load_api_keys(_documento(_HASH))

    assert clave.hash == _HASH


def test_uppercase_hex_is_accepted() -> None:
    """SHA-256 en mayusculas sigue siendo SHA-256. Rechazarlo seria una
    trampa para quien genere el secreto con otra herramienta."""
    (clave,) = load_api_keys(_documento(_HASH.upper()))

    assert clave.hash.lower() == _HASH


def test_the_plaintext_key_is_nowhere_in_the_loaded_object() -> None:
    """CA-5: ningun campo del objeto cargado contiene la clave."""
    (clave,) = load_api_keys(_documento(_HASH))

    valores = " ".join(str(v) for v in vars(clave).values())
    assert _CLAVE not in valores


def test_repr_exposes_neither_the_key_nor_the_hash() -> None:
    """CA-5, segunda linea de defensa: el `repr` acaba en el log de
    cualquier excepcion que arrastre el objeto. El hash no es la clave,
    pero permite fuerza bruta offline contra un formato conocido."""
    (clave,) = load_api_keys(_documento(_HASH))

    representacion = repr(clave)
    assert _CLAVE not in representacion
    assert _HASH not in representacion
    assert "k_recruiter_01" in representacion  # el key_id si: RFC-0005 6.2
