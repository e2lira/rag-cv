"""Verificacion de API Keys y roles -- RFC-0005 6.

En el servidor solo vive `sha256(clave)`, nunca la clave (6.1). La
comparacion es de tiempo constante y **todos los fallos son el mismo fallo**:
no se distingue inexistente de revocada o expirada, porque distinguirlos es
un oraculo para un atacante (6.2).
"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

# 64 digitos hexadecimales: la forma de sha256().hexdigest(). Se valida el
# formato y no el contenido porque un hash no se puede "verificar" -- pero
# si distingue un digest de una clave en claro, que es lo que importa.
_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")

# `admin` incluye lo de `read` (RFC-0005 6.3). En minusculas y sin
# variantes: aceptar `READ` invitaria a que dos despliegues discrepen sobre
# que significa una clave.
_ROLES: dict[str, tuple[str, ...]] = {
    "read": ("read",),
    "admin": ("read", "admin"),
}


@dataclass(frozen=True)
class ApiKey:
    """Una clave cargada de `API_KEYS_JSON` -- RFC-0005 6.1."""

    id: str
    hash: str = field(repr=False)
    role: str
    label: str = field(repr=False)
    expires_at: datetime | None
    active: bool

    def is_usable(self, *, now: datetime | None = None) -> bool:
        """Activa y no expirada -- RFC-0005 6.2."""
        if not self.active:
            return False
        if self.expires_at is None:
            return True
        return self.expires_at > (now or datetime.now(UTC))


class ApiKeysConfigError(RuntimeError):
    """`API_KEYS_JSON` ausente, invalido o sin ninguna clave utilizable.

    RFC-0005 10: el proceso no arranca. Sin claves no hay autenticacion
    posible, y arrancar sin ella deja la API abierta.
    """


def load_api_keys(raw: str | None) -> tuple[ApiKey, ...]:
    """Carga y valida `API_KEYS_JSON` (RFC-0005 6.1, CA-25)."""
    if raw is None or not raw.strip():
        raise ApiKeysConfigError("API_KEYS_JSON esta ausente o vacio")

    try:
        documento = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiKeysConfigError("API_KEYS_JSON no es JSON valido") from exc

    entradas = documento.get("keys") if isinstance(documento, dict) else None
    if not entradas:
        raise ApiKeysConfigError("API_KEYS_JSON no declara ninguna clave en 'keys'")

    claves = tuple(_construir(entrada) for entrada in entradas)
    if not any(clave.is_usable() for clave in claves):
        # Una API cuyo unico efecto posible es 401 no esta lista (RFC-0005 10).
        raise ApiKeysConfigError("API_KEYS_JSON no tiene ninguna clave activa y sin expirar")
    return claves


def _construir(entrada: dict[str, object]) -> ApiKey:
    expira = entrada.get("expires_at")
    digest = str(entrada["hash"])
    if not _SHA256_HEX.match(digest):
        # RFC-0005 6.1: el servidor guarda sha256(clave), nunca la clave.
        # Sin esta comprobacion, un secreto mal escrito deja la clave en
        # claro en memoria -- y ademas queda roto en silencio, porque
        # verify_api_key compara un digest contra algo que no lo es y la
        # clave legitima nunca autentica. El id (no el valor) va en el
        # mensaje: es lo unico que se puede publicar (6.2).
        raise ApiKeysConfigError(
            f"La clave {entrada['id']!r} no trae un SHA-256 en 'hash'. "
            "Se guarda el hash de la clave, nunca la clave."
        )
    return ApiKey(
        id=str(entrada["id"]),
        hash=digest,
        role=str(entrada["role"]),
        label=str(entrada.get("label", "")),
        expires_at=datetime.fromisoformat(str(expira)) if expira else None,
        active=bool(entrada.get("active", False)),
    )


def verify_api_key(presented: str | None, keys: tuple[ApiKey, ...]) -> ApiKey | None:
    """Devuelve la clave que corresponde, o None -- RFC-0005 6.2, CA-4.

    Recorre **todas** las claves aunque ya haya coincidencia: cortar en la
    primera filtra por posicion en la lista lo que `compare_digest` protege
    por contenido.
    """
    if not presented:
        return None

    presentado = hashlib.sha256(presented.encode()).hexdigest()
    encontrada: ApiKey | None = None
    for clave in keys:
        # El hash cargado puede venir en mayusculas (6.1 acepta las dos
        # formas); compare_digest es sensible a mayusculas, asi que se
        # normaliza antes de comparar, no despues.
        if hmac.compare_digest(presentado, clave.hash.lower()) and clave.is_usable():
            encontrada = clave
    return encontrada


def has_role(key: ApiKey, required: str) -> bool:
    """Rol suficiente para la ruta -- RFC-0005 6.3. `admin` incluye `read`.

    No mira vigencia: eso es de `verify_api_key` (6.2). Separar las dos
    preguntas es lo que permite responder 401 y 403 de forma distinta -- si
    una clave expirada diera 403, filtraria que existio.
    """
    # `.get(rol, ())` y no `[rol]`: un rol desconocido no alcanza nada, pero
    # tampoco revienta. Un KeyError aqui seria un 500 en vez de un 403, y un
    # secreto mal escrito no debe tumbar la API.
    return required in _ROLES.get(key.role, ())
