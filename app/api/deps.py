"""Dependencias de las rutas `/v1/*` -- RFC-0005 6, 7.

`app/api/` no contiene logica de negocio ni SQL (RFC-0001 62): la decision de
si una clave vale la toma `app/core/security.py`, y el contador de cuota lo
incrementa `app/core/rate_buckets.py`. Aqui solo se traduce esa decision a
codigo HTTP y cabeceras.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import HTTPException, Request, Response

from app.core.rate_buckets import (
    DAY,
    MINUTE,
    RateLimitDecision,
    decide,
    increment_rate_bucket,
    window_start,
)
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


MAX_BODY_BYTES = 8 * 1024
PAYLOAD_TOO_LARGE_MESSAGE = "El cuerpo de la peticion supera el maximo permitido."


async def enforce_body_limit(request: Request) -> None:
    """Rechaza con 413 un cuerpo por encima del tope (RFC-0005 7, CA-7).

    Como dependencia, corre ANTES del handler: el agente no se invoca y el
    gasto de tokens no ocurre.

    Dos comprobaciones, y las dos hacen falta:

    1. `Content-Length`, cuando viene: corta sin leer un solo byte.
    2. **El tamano real mientras se lee**, porque una peticion troceada
       (`Transfer-Encoding: chunked`) no declara longitud. Mirar solo la
       cabecera deja el limite a merced del cliente: para saltarselo basta
       con no declararla.

    La lectura aborta en cuanto pasa el tope, asi que nunca se retienen mas
    de `MAX_BODY_BYTES` mas un fragmento -- 8 KB, no el cuerpo entero.
    """
    declarado = request.headers.get("content-length")
    if declarado is not None and declarado.isdigit() and int(declarado) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail=PAYLOAD_TOO_LARGE_MESSAGE)

    tamano = 0
    fragmentos: list[bytes] = []
    async for fragmento in request.stream():
        tamano += len(fragmento)
        if tamano > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail=PAYLOAD_TOO_LARGE_MESSAGE)
        fragmentos.append(fragmento)

    # El flujo se consume una sola vez: se deja el cuerpo en la cache que
    # `Request.body()` habria rellenado, para que el handler pueda leerlo.
    request._body = b"".join(fragmentos)  # noqa: SLF001


RATE_LIMITED_MESSAGE = "Has superado el limite de peticiones."


def rate_limiter(key_id: str) -> Callable[[Request, Response], None]:
    """Dependencia de cuota: incrementa las dos cubetas y traduce el
    veredicto a `429` con las cabeceras de RFC-0005 7.

    Recibe el `key_id` en vez de leerlo de la peticion para poder montarse
    tambien donde la clave ya se resolvio; la decision la toma
    `app/core/rate_buckets.py` (RFC-0001 62: aqui no hay logica ni SQL).
    """

    def dependencia(request: Request, response: Response) -> None:
        estado = request.app.state
        ahora = datetime.now(UTC)

        # Las dos, siempre (RFC-0005 7): si solo se incrementara la que se
        # consulta, la cubeta de dia nunca llegaria a su tope.
        with estado.db_pool.connection() as conn:
            counts = {
                kind: increment_rate_bucket(
                    conn, key_id=key_id, window_kind=kind, window_start=window_start(kind, ahora)
                )
                for kind in (MINUTE, DAY)
            }

        veredicto = decide(
            counts,
            now=ahora,
            per_minute=estado.rate_limit_per_minute,
            per_day=estado.rate_limit_per_day,
        )
        cabeceras = _cabeceras_de_cuota(veredicto)
        if not veredicto.allowed:
            cabeceras["Retry-After"] = str(veredicto.retry_after_seconds)
            raise HTTPException(status_code=429, detail=RATE_LIMITED_MESSAGE, headers=cabeceras)

        response.headers.update(cabeceras)

    return dependencia


def _cabeceras_de_cuota(veredicto: RateLimitDecision) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(veredicto.limit),
        "X-RateLimit-Remaining": str(veredicto.remaining),
        "X-RateLimit-Reset": str(int(veredicto.reset_at.timestamp())),
    }


def current_key(request: Request) -> ApiKey:
    """La clave ya verificada para esta peticion."""
    clave: ApiKey | None = getattr(request.state, _KEY_STATE, None)
    if clave is None:  # pragma: no cover -- solo si se usa sin require_role
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_MESSAGE)
    return clave
