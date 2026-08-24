"""Construccion de la aplicacion HTTP -- RFC-0005 9.

Es una fabrica y no un `app` de modulo porque `/docs` depende de `APP_ENV`
(9): la decision hay que tomarla al construir, y una prueba necesita poder
construir dos veces con entornos distintos.
"""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Arma la aplicacion con su manejo de errores y su politica de `/docs`."""
    raise NotImplementedError  # RFC-0005 9: pendiente de su propio ciclo
