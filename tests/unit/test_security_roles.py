"""RFC-0005 6.3: `admin` incluye lo de `read`; `read` no alcanza `admin`.

El 403 que traduce este `False` es del router (`app/api/deps.py`); aqui se
prueba la jerarquia, no como se comunica.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.security import ApiKey, has_role

pytestmark = pytest.mark.unit


def _clave(rol: str, *, activa: bool = True, expirada: bool = False) -> ApiKey:
    ayer = datetime.now(UTC) - timedelta(days=1)
    return ApiKey(
        id=f"k_{rol}",
        hash="0" * 64,
        role=rol,
        label=rol,
        expires_at=ayer if expirada else None,
        active=activa,
    )


@pytest.mark.parametrize(
    ("rol", "exigido", "permitido"),
    [
        ("read", "read", True),
        ("admin", "read", True),
        ("admin", "admin", True),
        ("read", "admin", False),
    ],
)
def test_role_hierarchy(rol: str, exigido: str, permitido: bool) -> None:
    """RFC-0005 6.3: la tabla de permisos, entrada por entrada."""
    assert has_role(_clave(rol), exigido) is permitido


@pytest.mark.parametrize("rol", ["", "superadmin", "READ", "root"])
def test_an_unknown_role_grants_nothing(rol: str) -> None:
    """Un rol que no esta en la tabla no alcanza nada, y no revienta: un
    `KeyError` aqui seria un 500 en vez de un 403, y un secreto mal escrito
    no debe tumbar la API. `READ` en mayusculas tampoco vale -- los roles de
    6.3 se escriben en minusculas, y aceptar variantes invita a que dos
    despliegues discrepen sobre que significa una clave."""
    assert has_role(_clave(rol), "read") is False
    assert has_role(_clave(rol), "admin") is False


def test_has_role_does_not_consider_expiry_or_revocation() -> None:
    """La vigencia es de `verify_api_key` (6.2), no de aqui: separar las dos
    preguntas es lo que permite responder 401 y 403 de forma distinta.

    Si `has_role` mirara tambien la vigencia, una clave expirada daria 403 en
    vez de 401 y filtraria que existio alguna vez -- el oraculo que 6.2
    prohibe."""
    assert has_role(_clave("admin", activa=False), "admin") is True
    assert has_role(_clave("admin", expirada=True), "admin") is True
