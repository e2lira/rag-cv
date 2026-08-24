"""Dependencias de las rutas `/v1/*` -- RFC-0005 6, 7.

`app/api/` no contiene logica de negocio ni SQL (RFC-0001 62): la decision de
si una clave vale la toma `app/core/security.py`, y el contador de cuota lo
incrementa `app/core/rate_buckets.py`. Aqui solo se traduce esa decision a
codigo HTTP y cabeceras.
"""

from collections.abc import Callable

from fastapi import HTTPException, Request

from app.core.security import ApiKey, has_role, verify_api_key

# RFC-0005 6.2: un unico 401 para toda causa. No se distingue clave
# inexistente de revocada o expirada -- distinguirlas es un oraculo.
UNAUTHORIZED_MESSAGE = "API Key ausente o invalida."
FORBIDDEN_MESSAGE = "El rol de esta API Key no alcanza para esta ruta."

_KEY_STATE = "rfc0005_api_key"
_BEARER = "bearer "


def presented_key(request: Request) -> str | None:
    """Lee la clave de `X-API-Key` o de `Authorization: Bearer` (RFC-0005 6.2)."""
    directa = request.headers.get("X-API-Key")
    if directa:
        return directa

    autorizacion = request.headers.get("Authorization", "")
    if autorizacion.lower().startswith(_BEARER):
        return autorizacion[len(_BEARER) :].strip() or None
    return None


def require_role(required: str) -> Callable[[Request], ApiKey]:
    """Dependencia que exige clave valida y rol suficiente (RFC-0005 6.2, 6.3)."""

    def dependencia(request: Request) -> ApiKey:
        claves: tuple[ApiKey, ...] = getattr(request.app.state, "api_keys", ())
        clave = verify_api_key(presented_key(request), claves)
        if clave is None:
            # Mismo 401 para ausente, inexistente, revocada y expirada.
            raise HTTPException(status_code=401, detail=UNAUTHORIZED_MESSAGE)
        if not has_role(clave, required):
            # 403, no 401: la credencial es valida, lo que falta es permiso.
            raise HTTPException(status_code=403, detail=FORBIDDEN_MESSAGE)

        # El key_id (nunca la clave) queda disponible para el log del turno
        # y para el aislamiento por conversacion (RFC-0005 6.2, 6.3).
        setattr(request.state, _KEY_STATE, clave)
        return clave

    return dependencia


def current_key(request: Request) -> ApiKey:
    """La clave ya verificada para esta peticion."""
    clave: ApiKey | None = getattr(request.state, _KEY_STATE, None)
    if clave is None:  # pragma: no cover -- solo si se usa sin require_role
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_MESSAGE)
    return clave
