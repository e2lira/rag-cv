"""RFC-0011 CA-11: no hay rutas literales con separadores ni open() sin encoding.

Se prueba que ruff, con la configuracion real del proyecto, detecta ambos
patrones -- no que el codigo actual este limpio (eso ya lo garantiza el CI en
cada PR); esto es una prueba de que la regla sigue activa.
"""

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]

_VIOLATING_CODE = """\
import os

def build_path(base, name):
    return os.path.join(base, name)

def read(path):
    return open(path).read()
"""


def test_ruff_flags_os_path_join_and_open_without_encoding(tmp_path: Path) -> None:
    scratch = tmp_path / "violations.py"
    scratch.write_text(_VIOLATING_CODE, encoding="utf-8")

    ruff_bin = Path(sys.executable).parent / ("ruff.exe" if sys.platform == "win32" else "ruff")
    result = subprocess.run(
        [str(ruff_bin), "check", "--config", str(_ROOT / "pyproject.toml"), str(scratch)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, "ruff no marco ninguna violacion"
    assert "PTH118" in result.stdout, f"esperaba PTH118 (os.path.join):\n{result.stdout}"
    assert "PTH123" in result.stdout, f"esperaba PTH123 (open() sin Path.open()):\n{result.stdout}"
