"""Punto de entrada de la aplicacion.

Esqueleto de RFC-0011 (docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #2, #5.2):
solo /readyz, sin base de datos ni logica de negocio. RFC-0005 lo amplia con
el contrato real de la API.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.platform import assert_compatible_loop


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    assert_compatible_loop()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ok"}
