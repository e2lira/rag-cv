"""RFC-0006 CA-19: infra/sql y su workflow quedan retirados una vez que
Alembic absorbe su contrato completo (RFC-0006 2.2).

Deliberadamente SIN la marca `unit`: toca disco fuera del arbol de app/tests
(RFC-0014 5, regla transversal sobre I/O en unitarias).
"""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_RETIRED_PATHS = (
    "infra/sql/001_initialize_rag_cv.sql",
    "infra/sql/tests/001_initialize_rag_cv_verify.sql",
    ".github/workflows/verify-database-bootstrap.yml",
)


def test_legacy_bootstrap_files_removed() -> None:
    existing = [path for path in _RETIRED_PATHS if (_REPO_ROOT / path).exists()]
    assert not existing, f"deberian estar retirados: {existing}"


def test_no_live_references_to_legacy_bootstrap() -> None:
    offenders = []
    for path in _REPO_ROOT.rglob("*.md"):
        if "docs/auditorias" in path.as_posix() or "docs/rfc" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        if "infra/sql" in text or "verify-database-bootstrap" in text:
            offenders.append(str(path.relative_to(_REPO_ROOT)))

    assert not offenders, f"referencias vivas a infra/sql retirado: {offenders}"
