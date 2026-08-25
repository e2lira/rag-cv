"""Vivacidad y preparacion -- RFC-0005 3.1.

La diferencia entre los dos es el punto: `/healthz` dice si el proceso
vive, `/readyz` si puede atender. Confundirlos hace que `systemd` reinicie
por una base de datos caida, que no es un fallo del proceso.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_OK = "ok"
_ERROR = "error"

# Segundos para adquirir conexion en la comprobacion de preparacion.
_CHECK_TIMEOUT = 2.0


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Vivacidad: **no toca ninguna dependencia** (RFC-0005 3.1, CA-21).

    Si abriera una conexion, se caeria con la base y `systemd` reiniciaria
    un proceso que estaba vivo -- justo cuando reiniciar no arregla nada.
    Y aunque `build_readiness` se comiera el fallo y el 200 se mantuviera,
    cada sondeo pagaria la espera del pool: la sonda mas barata del sistema
    seria la mas cara.
    """
    return {"status": _OK}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    """Preparacion: base accesible, corpus indexado, configuracion valida,
    y el SHA desplegado (RFC-0005 3.1, CA-20)."""
    checks, listo = build_readiness(request.app.state)
    return JSONResponse(
        status_code=200 if listo else 503,
        content={
            "status": "ready" if listo else "not_ready",
            "commit_sha": _commit_sha(request.app.state),
            "checks": checks,
        },
    )


def _commit_sha(app_state: Any) -> str | None:
    """El commit desplegado, leido del artefacto de la release.

    No se ejecuta `git`: el VPS no tiene el repositorio (RFC-0020 6). Si no
    esta disponible va `null` -- no se inventa, porque el valor entero
    existe para poder comprobar que corre lo que se dijo que corre.
    """
    sha: str | None = getattr(app_state, "commit_sha", None)
    return sha or None


def build_readiness(app_state: Any) -> tuple[dict[str, str], bool]:
    """Comprobaciones de `/readyz` y si todas pasan (RFC-0005 3.1).

    Devuelve el detalle por comprobacion, no un booleano suelto: el cliente
    tiene que saber **cual** fallo. No es filtrado de interno (I-6) porque
    son nombres fijos, no trazas ni recursos.
    """
    # `config` ya paso: sin ella el proceso no habria arrancado (RFC-0021).
    checks = {"database": _ERROR, "corpus_indexed": _ERROR, "config": _OK}

    try:
        # Acotado a proposito: el pool espera 30 s por defecto, y una sonda
        # de preparacion que tarda 30 s en decir "no estoy listo" es inutil
        # -- `systemd` y nginx la matan antes, asi que el 503 nunca se lee.
        # Mas vale responder "no lista" pronto que la verdad tarde.
        with app_state.db_pool.connection(timeout=_CHECK_TIMEOUT) as conn, conn.cursor() as cur:
            checks["database"] = _OK
            cur.execute("SELECT EXISTS (SELECT 1 FROM cv_chunks WHERE doc_id = %s)", ("cv",))
            fila = cur.fetchone()
            checks["corpus_indexed"] = _OK if fila and fila[0] else _ERROR
    except Exception:
        # Se captura ancho a proposito: la base puede fallar de muchas
        # formas y todas significan lo mismo aqui -- no esta lista. El
        # detalle no sale al cliente (I-6); lo lleva el log del turno.
        pass

    return checks, all(estado == _OK for estado in checks.values())
