"""RFC-0011 CA-4: arrancar con el CLI de uvicorn en Windows produce un error
claro sobre el bucle de eventos, no un error de base de datos.

Nombre de archivo y de test fijados por el propio criterio de aceptacion.
"""

import asyncio
import sys

import pytest

from app.core.platform import assert_compatible_loop, configure_event_loop

pytestmark = pytest.mark.unit


@pytest.mark.skipif(sys.platform != "win32", reason="ProactorEventLoop es especifico de Windows")
def test_proactor_detected() -> None:
    async def _run() -> None:
        assert_compatible_loop()

    loop = asyncio.ProactorEventLoop()
    try:
        with pytest.raises(RuntimeError, match="Bucle de eventos incompatible"):
            loop.run_until_complete(_run())
    finally:
        loop.close()


@pytest.mark.skipif(sys.platform != "win32", reason="la politica solo aplica en Windows")
def test_configure_event_loop_sets_selector_policy_on_windows() -> None:
    configure_event_loop()
    policy = asyncio.get_event_loop_policy()
    assert isinstance(policy, asyncio.WindowsSelectorEventLoopPolicy)
