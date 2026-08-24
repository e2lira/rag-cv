"""Construccion de la aplicacion HTTP -- RFC-0005 9.

Es una fabrica y no un `app` de modulo porque `/docs` depende de `APP_ENV`
(9): la decision hay que tomarla al construir, y una prueba necesita poder
construir dos veces con entornos distintos.
"""

from fastapi import FastAPI

from app.api.errors import install_error_handling
from app.core.settings import Settings

_PROD = "prod"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Arma la aplicacion con su manejo de errores y su politica de `/docs`."""
    settings = settings or Settings()

    # docs_url=None desregistra la ruta: no queda apagada, no existe. Un 404
    # de ruta inexistente no revela que la documentacion este ahi detras.
    publica_docs = settings.app_env != _PROD
    app = FastAPI(
        docs_url="/docs" if publica_docs else None,
        redoc_url="/redoc" if publica_docs else None,
        openapi_url="/openapi.json" if publica_docs else None,
    )

    install_error_handling(app)
    return app
