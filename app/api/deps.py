"""Dependencias de las rutas `/v1/*` -- RFC-0005 6, 7.

`app/api/` no contiene logica de negocio ni SQL (RFC-0001 62): la decision de
si una clave vale la toma `app/core/security.py`, y el contador de cuota lo
incrementa `app/core/rate_buckets.py`. Aqui solo se traduce esa decision a
codigo HTTP y cabeceras.
"""

from collections.abc import Callable

from fastapi import Request

from app.core.security import ApiKey

# RFC-0005 6.2: un unico 401 para toda causa. No se distingue clave
# inexistente de revocada o expirada -- distinguirlas es un oraculo.
UNAUTHORIZED_MESSAGE = "API Key ausente o invalida."


def presented_key(request: Request) -> str | None:
    """Lee la clave de `X-API-Key` o de `Authorization: Bearer` (RFC-0005 6.2)."""
    raise NotImplementedError  # RFC-0005 6.2: pendiente de su propio ciclo


def require_role(required: str) -> Callable[[Request], ApiKey]:
    """Dependencia que exige clave valida y rol suficiente (RFC-0005 6.2, 6.3)."""
    raise NotImplementedError  # RFC-0005 6.2: pendiente de su propio ciclo


def current_key(request: Request) -> ApiKey:
    """La clave ya verificada para esta peticion."""
    raise NotImplementedError  # RFC-0005 6.2: pendiente de su propio ciclo
