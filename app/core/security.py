"""Verificacion de API Keys y roles -- RFC-0005 6.

En el servidor solo vive `sha256(clave)`, nunca la clave (6.1). La
comparacion es de tiempo constante y **todos los fallos son el mismo fallo**:
no se distingue inexistente de revocada o expirada, porque distinguirlos es
un oraculo para un atacante (6.2).
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime


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
    return ApiKey(
        id=str(entrada["id"]),
        hash=str(entrada["hash"]),
        role=str(entrada["role"]),
        label=str(entrada.get("label", "")),
        expires_at=datetime.fromisoformat(str(expira)) if expira else None,
        active=bool(entrada.get("active", False)),
    )


def verify_api_key(presented: str | None, keys: tuple[ApiKey, ...]) -> ApiKey | None:
    """Devuelve la clave que corresponde, o None -- RFC-0005 6.2, CA-4."""
    raise NotImplementedError  # RFC-0005 6.2: pendiente de su propio ciclo


def has_role(key: ApiKey, required: str) -> bool:
    """Rol suficiente para la ruta -- RFC-0005 6.3. `admin` incluye `read`."""
    raise NotImplementedError  # RFC-0005 6.3: pendiente de su propio ciclo
