"""RFC-0006 CA-19 / A-12: infra/sql y su workflow quedan retirados una vez que
Alembic absorbe su contrato completo (RFC-0006 2.2), y ningun documento sigue
prescribiendolos.

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

_RETIRED_NAMES = ("infra/sql", "verify-database-bootstrap")

# Un documento PUEDE nombrar lo retirado -- RFC-0006 2.2 explica por que se
# retiro, y RFC-0016 3.3 lo cita como el estado del que parte su decision.
# Lo que no puede es prescribirlo como si siguiera vivo. La diferencia
# verificable: el documento debe declarar en algun lugar que ya no existe.
# Raices, no palabras completas: "retir" cubre retirado/retirada/retiró/retiran,
# "ustitu" cubre sustituido/sustituye/Sustituido sin depender de la tilde ni de
# la mayuscula inicial.
_RETIREMENT_MARKERS = ("retir", "ustitu")

# Los informes de auditoria se archivan tal cual los emitio el Auditor y no se
# editan (docs/auditorias/README.md); citan el estado del PR en su momento.
_EXCLUDED_DIRS = ("docs/auditorias",)


def test_legacy_bootstrap_files_removed() -> None:
    existing = [path for path in _RETIRED_PATHS if (_REPO_ROOT / path).exists()]
    assert not existing, f"deberian estar retirados: {existing}"


def test_no_live_references_to_legacy_bootstrap() -> None:
    offenders = []
    for path in _REPO_ROOT.rglob("*.md"):
        posix = path.as_posix()
        if any(excluded in posix for excluded in _EXCLUDED_DIRS):
            continue
        text = path.read_text(encoding="utf-8")
        if not any(name in text for name in _RETIRED_NAMES):
            continue
        if not any(marker in text for marker in _RETIREMENT_MARKERS):
            offenders.append(str(path.relative_to(_REPO_ROOT)))

    assert not offenders, f"documentos que nombran lo retirado sin declararlo retirado: {offenders}"
