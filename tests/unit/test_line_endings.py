"""RFC-0011 CA-8: ningun .sh ni el Dockerfile tienen CRLF.

Un .sh con CRLF que llegue al VPS falla con "bad interpreter: /bin/bash^M"
(RFC-0011 #5.4). Se verifica sobre los archivos rastreados por git, no sobre
el disco: lo que importa es lo que se sube.

Deliberadamente SIN la marca `unit` (auditoria PR #16): invoca git como
subproceso y lee bytes del disco -- "test unitario que abre socket, toca
disco o base de datos" es Mayor segun la rubrica transversal del proceso
(PROMPT-AUDITOR.md #2). Se ejecuta con `pytest tests/unit/test_line_endings.py`
directo, no via `invoke test` (que filtra por -m unit).
"""

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _tracked_shell_and_dockerfiles() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.sh", "Dockerfile"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def test_no_tracked_sh_or_dockerfile_has_crlf() -> None:
    offenders = [
        path for path in _tracked_shell_and_dockerfiles() if b"\r\n" in (_ROOT / path).read_bytes()
    ]
    assert not offenders, f"CRLF encontrado en: {offenders}"
