"""Compatibilidad de plataforma para el bucle de eventos en Windows.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #5.1.
"""

import asyncio
import sys


def configure_event_loop() -> None:
    """En Windows, psycopg async exige SelectorEventLoop. Debe ejecutarse
    ANTES de que se cree cualquier bucle de eventos."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def assert_compatible_loop() -> None:
    """Comprobacion de arranque: falla claro en vez de fallar en la primera consulta."""
    if sys.platform == "win32":
        loop = asyncio.get_running_loop()
        if type(loop).__name__ == "ProactorEventLoop":
            raise RuntimeError(
                "Bucle de eventos incompatible con psycopg async. "
                "Arranca con 'python -m app.dev_server', no con el CLI de uvicorn."
            )


def default_test_db_mode() -> str:
    """TEST_DB_MODE por defecto si no se fija explicito -- RFC-0011 #8.

    Unica funcion que consulta sys.platform para esta decision: quien la
    necesite (tests/conftest.py) la importa, no repite la comprobacion."""
    return "local" if sys.platform == "win32" else "container"
