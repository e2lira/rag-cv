"""Endpoints administrativos -- RFC-0005 3.2 (RFC-0001 4: sin logica ni SQL).

Todo `/v1/admin/*` exige rol `admin` (6.3), tambien el que solo lee: si se
protegiera unicamente el que escribe, una clave `read` podria enumerar el
estado de la ingesta -- que es informacion de operacion, no de consulta.
"""

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse

from app.api.deps import require_role
from app.db.jobs import NoCurrentCorpus, enqueue_reindex, get_job

router = APIRouter(prefix="/v1/admin", dependencies=[Depends(require_role("admin"))])

_SIN_CORPUS = "No hay una version vigente del corpus que reindexar."
_SIN_TRABAJO = "El trabajo no existe."
_TIEMPO_DE_ESPERA = 5.0


@router.post("/reindex", status_code=202)
async def reindex(request: Request) -> JSONResponse:
    """Encola la reindexacion del corpus vigente (RFC-0005 3.2, CA-24).

    Sin cuerpo, y sin campo `force`: con `idempotency_key` UNIQUE no existe
    forma de encolar un duplicado para el mismo contenido, asi que `force`
    seria contrato muerto. Para reindexar contenido ya procesado el camino
    es el de RFC-0019 7 -- cambiar el archivo --, no un parametro de la API.
    """
    try:
        with request.app.state.db_pool.connection(timeout=_TIEMPO_DE_ESPERA) as conn:
            job_id, estado = enqueue_reindex(conn)
    except NoCurrentCorpus as exc:
        raise HTTPException(status_code=404, detail=_SIN_CORPUS) from exc

    return JSONResponse(status_code=202, content={"job_id": job_id, "state": estado})


@router.get("/jobs/{job_id}")
async def job_status(job_id: str, request: Request) -> dict[str, Any]:
    """El estado de un trabajo de ingesta (RFC-0005 3.2)."""
    with request.app.state.db_pool.connection(timeout=_TIEMPO_DE_ESPERA) as conn:
        trabajo = get_job(conn, job_id=job_id)

    if trabajo is None:
        raise HTTPException(status_code=404, detail=_SIN_TRABAJO)
    return trabajo
