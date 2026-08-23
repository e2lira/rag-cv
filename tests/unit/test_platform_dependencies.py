"""RFC-0011 CA-6: uvloop no se instala en Windows y si en Linux.

Se verifica por inspeccion de pyproject.toml, no por instalacion real: instalar
uvloop en Windows fallaria (sin binarios), y eso no es lo que este test prueba.
"""

import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_uvloop_is_declared_only_for_non_windows() -> None:
    root = Path(__file__).resolve().parents[2]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    uvloop_specs = [dep for dep in data["project"]["dependencies"] if dep.startswith("uvloop")]

    assert uvloop_specs, "uvloop no esta declarado como dependencia"
    assert "sys_platform != 'win32'" in uvloop_specs[0], (
        f"uvloop debe llevar el marcador de plataforma, tiene: {uvloop_specs[0]!r}"
    )
