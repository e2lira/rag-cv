"""Punto de entrada de la aplicacion.

Esqueleto de RFC-0011 (docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #2, #5.2):
solo /readyz, sin base de datos ni logica de negocio. RFC-0005 lo amplia con
el contrato real de la API.
"""

from fastapi import FastAPI

app = FastAPI()


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    raise NotImplementedError
