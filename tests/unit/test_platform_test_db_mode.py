"""Auditoria PR #16, T-10: ninguna decision depende del sistema operativo
fuera de app/core/platform.py. Mayor -- rubrica transversal.

tests/conftest.py decidia TEST_DB_MODE por defecto consultando sys.platform
directamente (RFC-0011 #8), lo que dispersaba la politica de plataforma
fuera del unico modulo permitido."""

import pytest

from app.core.platform import default_test_db_mode

pytestmark = pytest.mark.unit


def test_default_is_local_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.platform.sys.platform", "win32")
    assert default_test_db_mode() == "local"


def test_default_is_container_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.platform.sys.platform", "linux")
    assert default_test_db_mode() == "container"
