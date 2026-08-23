"""Resolucion del head de Alembic en tiempo de ejecucion -- RFC-0021 6."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"


def resolve_expected_head(alembic_ini_path: Path | None = None) -> str:
    """La cabeza del arbol de migraciones, leida del propio repositorio.

    No es una constante escrita a mano ni una variable de entorno: las dos
    quedan obsoletas en la siguiente migracion y nadie las actualiza
    (RFC-0021 6)."""
    cfg = Config(str(alembic_ini_path or _DEFAULT_ALEMBIC_INI))
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("el arbol de migraciones no tiene ninguna revision")
    return head
