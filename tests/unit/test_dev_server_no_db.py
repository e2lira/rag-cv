"""RFC-0021 CA-7: app/dev_server.py sigue siendo solo un lanzador -- fija la
politica del bucle de eventos y arranca app.main:app, sin adquirir el menor
import de psycopg, Settings ni startup_checks.

Criterio heredado de RFC-0014 6.1.2: dev_server.py no cambia en este RFC
(RFC-0021 3 lo dice explicitamente), asi que esta invariante ya la entrego
RFC-0011, sin tocar. No hay nada que poner en rojo con una implementacion
nueva -- lo unico que cuenta es la reversion (ver mensaje del commit)."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_FORBIDDEN_IMPORTS = ("psycopg", "app.core.settings", "app.core.startup_checks")


def test_dev_server_has_no_database_dependency() -> None:
    source = Path("app/dev_server.py").read_text(encoding="utf-8")
    for forbidden in _FORBIDDEN_IMPORTS:
        assert forbidden not in source, (
            f"app/dev_server.py importa {forbidden!r}: dejo de ser un lanzador "
            "sin logica propia (RFC-0021 CA-7 / RFC-0011 CA-5)"
        )
