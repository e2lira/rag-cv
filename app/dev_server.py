"""Lanzador de desarrollo para Windows.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #5.2.
El CLI de uvicorn no garantiza la politica del bucle de eventos: crea su
propio bucle antes de que el proceso pueda fijarla. Por eso el arranque en
DEV pasa por este lanzador, y no por el CLI directo.
"""

from app.core.platform import configure_event_loop

configure_event_loop()  # antes de importar/arrancar uvicorn

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8080,
        reload=True,
        loop="asyncio",  # nunca uvloop; no existe en Windows
        workers=1,  # reload y workers son incompatibles
    )
