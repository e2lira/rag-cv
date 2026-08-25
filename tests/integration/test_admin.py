"""RFC-0005 3.2: endpoints administrativos.

`/v1/admin/reindex` **encola, no ejecuta**: la ingesta la corre el proceso de
RFC-0019 desde el `crontab`, y la API que atiende consultas no debe
bloquearse reindexando. Este endpoint se acopla a ese reparto en vez de abrir
un segundo camino.
"""

from typing import Any

import psycopg
import pytest

from tests.integration.test_chat import _CLAVE, _clave_de_prueba, _cliente

pytestmark = pytest.mark.integration

_OBJETO = "corpus/cv.md"
_VERSION = "v1"


def _corpus_registrado(database_url: str) -> None:
    """Deja el corpus como version vigente, que es lo que reindexa."""
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO source_documents "
            "(object_key, source_version_id, source_fingerprint, content_sha256, "
            " ingestion_status, is_current) "
            "VALUES (%s, %s, 'fp', repeat('a', 64), 'indexed', true)",
            (_OBJETO, _VERSION),
        )
        conn.commit()


def _admin(database_url: str) -> Any:
    return _cliente(database_url, claves=(_clave_de_prueba(key_id="k_admin", role="admin"),))


def test_role_enforcement(database_url: str) -> None:
    """CA-3: el rol `read` en `/v1/admin/reindex` es `403`.

    No `404`: aqui no hay recurso ajeno que ocultar -- la ruta es publica y
    conocida, y lo que falta es permiso. El `404` de CA-8 protege la
    existencia de una conversacion; esto es otra cosa.
    """
    _corpus_registrado(database_url)

    respuesta = _cliente(database_url).post("/v1/admin/reindex", headers={"X-API-Key": _CLAVE})

    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["code"] == "forbidden"


def test_reindex_is_idempotent(database_url: str) -> None:
    """CA-24: dos peticiones sobre el mismo corpus devuelven el **mismo**
    `job_id` y dejan **una sola** fila en `ingestion_jobs`.

    La garantia no es del codigo de la API: es del `UNIQUE (idempotency_key)`
    de `ingestion_jobs` (RFC-0006 4). Por eso se comprueba tambien contando
    filas -- que las dos respuestas coincidan no probaria que no se encolo
    un segundo trabajo.
    """
    _corpus_registrado(database_url)
    cliente = _admin(database_url)

    primera = cliente.post("/v1/admin/reindex", headers={"X-API-Key": _CLAVE})
    segunda = cliente.post("/v1/admin/reindex", headers={"X-API-Key": _CLAVE})

    assert primera.status_code == 202, primera.text
    assert segunda.status_code == 202, segunda.text
    assert primera.json()["job_id"] == segunda.json()["job_id"]
    assert primera.json()["state"] == "pending"

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ingestion_jobs WHERE object_key = %s", (_OBJETO,))
        fila = cur.fetchone()

    assert fila is not None
    assert fila[0] == 1, "se encolo un segundo trabajo para el mismo contenido"


def test_reindex_takes_no_body(database_url: str) -> None:
    """RFC-0005 3.2: no hay campo `force`, y por eso no hay cuerpo.

    Con `idempotency_key` UNIQUE no existe forma de encolar un duplicado
    para el mismo contenido: un campo que el esquema impide seria contrato
    muerto. Para reindexar contenido ya procesado, el camino es el de
    RFC-0019 7 (cambiar el archivo), no un parametro de esta API.
    """
    _corpus_registrado(database_url)

    respuesta = _admin(database_url).post("/v1/admin/reindex", headers={"X-API-Key": _CLAVE})

    assert respuesta.status_code == 202


def test_job_status_is_readable(database_url: str) -> None:
    """RFC-0005 3.2: `GET /v1/admin/jobs/{job_id}` publica el estado."""
    _corpus_registrado(database_url)
    cliente = _admin(database_url)
    job_id = cliente.post("/v1/admin/reindex", headers={"X-API-Key": _CLAVE}).json()["job_id"]

    respuesta = cliente.get(f"/v1/admin/jobs/{job_id}", headers={"X-API-Key": _CLAVE})

    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["job_id"] == job_id
    assert cuerpo["state"] == "pending"
    assert cuerpo["attempt_count"] == 0
    assert cuerpo["error_code"] is None
    assert set(cuerpo) == {
        "job_id",
        "state",
        "attempt_count",
        "error_code",
        "started_at",
        "completed_at",
    }


def test_an_unknown_job_is_404(database_url: str) -> None:
    """RFC-0005 3.2: un `job_id` que no existe es `404`."""
    _corpus_registrado(database_url)

    respuesta = _admin(database_url).get(
        "/v1/admin/jobs/00000000-0000-0000-0000-000000000000",
        headers={"X-API-Key": _CLAVE},
    )

    assert respuesta.status_code == 404
    assert respuesta.json()["error"]["code"] == "not_found"


def test_reading_a_job_also_needs_admin(database_url: str) -> None:
    """RFC-0005 6.3: `/v1/admin/*` **entero** es del rol `admin`.

    Si solo se protegiera el que escribe, una clave `read` podria enumerar
    el estado de la ingesta -- que es informacion de operacion, no de
    consulta.
    """
    _corpus_registrado(database_url)

    respuesta = _cliente(database_url).get(
        "/v1/admin/jobs/00000000-0000-0000-0000-000000000000",
        headers={"X-API-Key": _CLAVE},
    )

    assert respuesta.status_code == 403
