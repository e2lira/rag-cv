"""Construccion de la aplicacion HTTP -- RFC-0005 9.

Es una fabrica y no un `app` de modulo porque `/docs` depende de `APP_ENV`
(9): la decision hay que tomarla al construir, y una prueba necesita poder
construir dos veces con entornos distintos.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.api.errors import install_error_handling
from app.core.settings import BootstrapSettings, Settings

_PROD = "prod"


def create_app(settings: Settings | None = None, *, lifespan: Any = None) -> FastAPI:
    """Arma la aplicacion con su manejo de errores y su politica de `/docs`.

    **Sin `settings` NO se construye `Settings()`.** Construir la
    configuracion completa aqui la validaria en tiempo de importacion de
    `app.main`, y eso rompe el orden que RFC-0021 5 declara normativo: el
    primer fallo visible al arrancar con el CLI de uvicorn tiene que ser el
    del bucle de eventos (RFC-0011 CA-4), no uno de configuracion. La
    validacion completa ocurre en el `lifespan`, donde RFC-0021 la puso.

    Lo que si se construye es `BootstrapSettings`, que trae solo las
    palancas que FastAPI necesita **al construirse** -- la politica de
    `/docs`, los origenes de CORS y el SHA desplegado -- y ninguna es un
    secreto. `Settings` hereda de ella, asi que no hay dos declaraciones del
    mismo alias, y el entorno se sigue leyendo unicamente en la capa de
    configuracion (RFC-0001 4).
    """
    arranque: BootstrapSettings = settings or BootstrapSettings()

    # docs_url=None desregistra la ruta: no queda apagada, no existe. Un 404
    # de ruta inexistente no revela que la documentacion este ahi detras.
    publica_docs = arranque.app_env != _PROD
    app = FastAPI(
        lifespan=lifespan,
        docs_url="/docs" if publica_docs else None,
        redoc_url="/redoc" if publica_docs else None,
        openapi_url="/openapi.json" if publica_docs else None,
    )

    # Lista blanca, vacia por defecto (RFC-0005 9, A-8): la v1 no tiene
    # frontend propio, y abrir `*` seria regalar la clave al primero que
    # inspeccione una pagina. Sin origenes declarados no se instala el
    # middleware -- montarlo con lista vacia solo anade trabajo por
    # peticion para no permitir nada.
    origenes = [o.strip() for o in arranque.cors_allowed_origins.split(",") if o.strip()]
    if origenes:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origenes,
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["X-API-Key", "Authorization", "Content-Type"],
        )

    install_error_handling(app)

    # El SHA se lee de la configuracion, que lo recibe del artefacto de la
    # release (RFC-0020 6): el VPS no tiene el repositorio, asi que no hay
    # `git` que consultar en tiempo de ejecucion.
    app.state.commit_sha = arranque.commit_sha
    app.include_router(health.router)
    return app
