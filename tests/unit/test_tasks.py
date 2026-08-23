"""RFC-0011 CA-12: invoke lint test funciona igual en Windows y en Ubuntu.

Deliberadamente SIN la marca `unit`: test_invoke_test_succeeds ejecuta
`invoke test`, que corre `pytest -m unit`. Si este archivo llevara esa
marca, se recogeria a si mismo y se llamaria en un bucle infinito de
subprocesos. Se ejecuta con `pytest tests/unit/test_tasks.py` directo.
"""

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_VENV_SCRIPTS = Path(sys.executable).parent


def _run_invoke(*args: str) -> subprocess.CompletedProcess[str]:
    invoke_bin = _VENV_SCRIPTS / ("invoke.exe" if sys.platform == "win32" else "invoke")
    env = os.environ.copy()
    env["PATH"] = f"{_VENV_SCRIPTS}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.run(
        [str(invoke_bin), *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_invoke_lint_succeeds() -> None:
    result = _run_invoke("lint")
    assert result.returncode == 0, result.stdout + result.stderr


def test_invoke_test_succeeds() -> None:
    result = _run_invoke("test")
    assert result.returncode == 0, result.stdout + result.stderr
