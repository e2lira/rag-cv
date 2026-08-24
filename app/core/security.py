"""Verificacion de API Keys y roles -- RFC-0005 6.

En el servidor solo vive `sha256(clave)`, nunca la clave (6.1). La
comparacion es de tiempo constante y **todos los fallos son el mismo fallo**:
no se distingue inexistente de revocada o expirada, porque distinguirlos es
un oraculo para un atacante (6.2).
"""

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
    raise NotImplementedError  # RFC-0005 6.1: pendiente de su propio ciclo


def verify_api_key(presented: str | None, keys: tuple[ApiKey, ...]) -> ApiKey | None:
    """Devuelve la clave que corresponde, o None -- RFC-0005 6.2, CA-4."""
    raise NotImplementedError  # RFC-0005 6.2: pendiente de su propio ciclo


def has_role(key: ApiKey, required: str) -> bool:
    """Rol suficiente para la ruta -- RFC-0005 6.3. `admin` incluye `read`."""
    raise NotImplementedError  # RFC-0005 6.3: pendiente de su propio ciclo
