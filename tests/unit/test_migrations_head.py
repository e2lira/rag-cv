"""RFC-0021 CA-4: expected_head se deriva del arbol de migraciones de Alembic
en tiempo de ejecucion, no de una constante escrita a mano ni de una
variable de entorno -- las dos quedan obsoletas en la siguiente migracion
y nadie las actualiza (RFC-0021 6)."""

from pathlib import Path

import pytest

from app.core.migrations import resolve_expected_head

pytestmark = pytest.mark.unit

_REVISION_TEMPLATE = """
revision = {revision!r}
down_revision = {down_revision!r}


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
"""


def test_resolves_current_repo_head() -> None:
    """Contra el arbol real de este repositorio: hoy una sola revision."""
    assert resolve_expected_head() == "0001_rfc0006_initial_schema"


def test_reflects_a_new_migration_without_code_changes(tmp_path: Path) -> None:
    """Agregar una revision al arbol cambia el head resuelto -- si esto
    fallara, expected_head seria una constante escrita a mano, no una
    lectura del arbol."""
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "0001_first.py").write_text(
        _REVISION_TEMPLATE.format(revision="0001_first", down_revision=None)
    )
    ini = tmp_path / "alembic.ini"
    ini.write_text(f"[alembic]\nscript_location = {tmp_path}\n")

    assert resolve_expected_head(ini) == "0001_first"

    (versions / "0002_second.py").write_text(
        _REVISION_TEMPLATE.format(revision="0002_second", down_revision="0001_first")
    )

    assert resolve_expected_head(ini) == "0002_second"
