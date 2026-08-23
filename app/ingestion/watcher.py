"""Sondeo del corpus en el VPS -- RFC-0019 3.

Punto de entrada `python -m app.ingestion.watcher`, invocado por el cron que
instala RFC-0020 7. Cada ejecucion es un ciclo completo con salida temprana:
la inmensa mayoria termina en un `stat` y una consulta indexada.
"""

import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from ulid import ULID

from app.core.settings import Settings
from app.ingestion.indexer import index_corpus
from app.retrieval.embedder import Embedder

# Viaja en source_metadata: si el algoritmo de deteccion cambia, el ledger
# dice con cual se observo cada version (RFC-0019 3 paso 5).
_DETECTOR_VERSION = 1

# RFC-0019 7.1: los cinco valores que admite ck_watcher_outcome.
OUTCOME_NO_CHANGE = "no_change"
OUTCOME_INDEXED = "indexed"
OUTCOME_UNSTABLE = "unstable"
OUTCOME_MISSING_CORPUS = "missing_corpus"
OUTCOME_FAILED = "failed"


@dataclass(frozen=True)
class WatcherReport:
    """Resultado de un ciclo del sondeo -- RFC-0019 3."""

    outcome: str
    source_version_id: str | None = None
    embed_calls: int = 0


@dataclass(frozen=True)
class _CurrentVersion:
    source_version_id: str
    source_fingerprint: str
    content_sha256: str


def fingerprint(path: Path) -> str:
    """Huella barata del paso 1 -- RFC-0019 3: `mtime_ns-size`, sin leer.

    Que no lea es el punto: con un CV que cambia unas pocas veces al ano, la
    inmensa mayoria de los ciclos se resuelven con esto y una consulta.
    """
    stat = path.stat()
    return f"{stat.st_mtime_ns}-{stat.st_size}"


def _current_version(conn: psycopg.Connection, object_key: str) -> _CurrentVersion | None:
    """La version vigente, si la hay -- `idx_source_one_current` garantiza
    que sea como mucho una (RFC-0006 4.5)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_version_id, source_fingerprint, content_sha256 "
            "FROM source_documents WHERE object_key = %s AND is_current",
            (object_key,),
        )
        row = cur.fetchone()

    if row is None:
        return None
    return _CurrentVersion(str(row[0]), str(row[1]), str(row[2]))


def _record_heartbeat(
    conn: psycopg.Connection,
    object_key: str,
    outcome: str,
    *,
    success: bool,
    detail: dict[str, object] | None = None,
) -> None:
    """RFC-0019 7.1: `last_run_at` siempre, `last_success_at` solo en exito.

    En el fracaso `last_success_at` CONSERVA su valor anterior en vez de
    anularse: es su antiguedad la que dispara la alerta de RFC-0010, y
    ponerlo a NULL en cada fallo perderia justo el dato que se vigila.
    """
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO watcher_heartbeat "
            "(object_key, last_run_at, last_success_at, last_outcome, detail) "
            "VALUES (%(key)s, now(), "
            "        CASE WHEN %(ok)s THEN now() ELSE NULL END, "
            "        %(outcome)s, %(detail)s::jsonb) "
            "ON CONFLICT (object_key) DO UPDATE SET "
            "  last_run_at = now(), "
            "  last_success_at = CASE WHEN %(ok)s THEN now() "
            "                        ELSE watcher_heartbeat.last_success_at END, "
            "  last_outcome = EXCLUDED.last_outcome, "
            "  detail = EXCLUDED.detail",
            {
                "key": object_key,
                "ok": success,
                "outcome": outcome,
                "detail": json.dumps(detail or {}),
            },
        )


async def run_once(
    conn: psycopg.Connection,
    embedder: Embedder,
    settings: Settings,
) -> WatcherReport:
    """Un ciclo completo del sondeo -- RFC-0019 3."""
    corpus_path = Path(settings.corpus_path)
    object_key = str(corpus_path.resolve())

    # Paso 1: un fichero ausente NO significa "el CV quedo vacio" -- se
    # registra el incidente y el indice vigente no se toca (CA-9).
    try:
        observed = fingerprint(corpus_path)
    except FileNotFoundError:
        _record_heartbeat(conn, object_key, OUTCOME_MISSING_CORPUS, success=False)
        conn.commit()
        return WatcherReport(outcome=OUTCOME_MISSING_CORPUS)

    # Paso 2: el atajo que hace barata la decision (CA-1). Es una comparacion
    # de coste, no de correccion: quien decide si re-embeber es index_corpus
    # (RFC-0019 6, A-1b).
    current = _current_version(conn, object_key)
    if current is not None and current.source_fingerprint == observed:
        _record_heartbeat(conn, object_key, OUTCOME_NO_CHANGE, success=True)
        conn.commit()
        return WatcherReport(outcome=OUTCOME_NO_CHANGE)

    # Paso 3: defensa en profundidad frente a una escritura en el sitio. No
    # es infalible y RFC-0019 4 lo dice sin adornos -- lo que elimina el
    # riesgo es el reemplazo atomico, que es normativo (CA-5).
    await asyncio.sleep(settings.watcher_stability_delay_seconds)
    if fingerprint(corpus_path) != observed:
        _record_heartbeat(conn, object_key, OUTCOME_UNSTABLE, success=False)
        conn.commit()
        return WatcherReport(outcome=OUTCOME_UNSTABLE)

    # Paso 4: es aqui, y solo aqui, donde se lee y se hashea el corpus.
    raw = corpus_path.read_bytes()
    content_sha256 = hashlib.sha256(raw).hexdigest()

    # RFC-0019 6 fila 1: contenido identico al vigente. Se actualiza la huella
    # de la fila vigente y se sale. Registrar una version por cada `touch`
    # engordaria el ledger sin que el corpus cambie, y obligaria a un ciclo
    # promover/degradar entre dos versiones de contenido identico.
    #
    # Actualizar la huella no es cosmetico: deja el atajo del paso 2 operativo
    # desde el ciclo siguiente, que es la razon de hacerlo en vez de ignorarla.
    if current is not None and current.content_sha256 == content_sha256:
        _refresh_fingerprint(conn, object_key, observed)
        _record_heartbeat(conn, object_key, OUTCOME_NO_CHANGE, success=True)
        conn.commit()
        return WatcherReport(outcome=OUTCOME_NO_CHANGE, source_version_id=current.source_version_id)

    # Pasos 5 y 6: la version y su trabajo se confirman ANTES de indexar, para
    # que una ejecucion que muera durante la ingesta deje traza de que la
    # deteccion ocurrio. El UNIQUE sobre idempotency_key absorbe el reintento.
    stat = corpus_path.stat()
    version_id = str(ULID())
    source_document_id = _register_version(
        conn,
        object_key,
        version_id,
        observed,
        content_sha256,
        {
            "inode": stat.st_ino,
            "mtime_ns": stat.st_mtime_ns,
            "size": stat.st_size,
            "detector_version": _DETECTOR_VERSION,
        },
    )
    _create_job(conn, object_key, version_id, source_document_id)
    conn.commit()

    # Paso 7a: reclamacion por lease ANTES de mutar nada (A-3). Si otra
    # ejecucion sostiene un lease VIVO sobre este object_key, esta sale sin
    # indexar: "la segunda no encuentra trabajo reclamable y sale" (RFC-0019
    # 9). Un lease CADUCADO no bloquea -- es lo que permite recuperarse de una
    # ejecucion que murio a mitad (5).
    idempotency_key = f"{object_key}@{version_id}"
    lease_token = _claim_job(conn, object_key, idempotency_key, settings.watcher_lease_seconds)
    conn.commit()
    if lease_token is None:
        _record_heartbeat(
            conn,
            object_key,
            OUTCOME_UNSTABLE,
            success=False,
            detail={"reason": "lease_held", "source_version_id": version_id},
        )
        conn.commit()
        return WatcherReport(outcome=OUTCOME_UNSTABLE, source_version_id=version_id)

    # Paso 7: la decision de re-embeber es de index_corpus, no de aqui
    # (RFC-0019 6, A-1b). Compara el content_hash de cada fragmento contra lo
    # que hay en cv_chunks: identico -> no embebe; reversion -> difiere y
    # re-embebe. Duplicar esa logica aqui podria contradecirla.
    report = await index_corpus(conn, embedder, corpus_path)

    # Paso 8: promocion y degradacion, una sola transaccion (RFC-0019 6.1).
    _promote(conn, object_key, version_id)
    _complete_job(conn, idempotency_key)

    # Paso 9.
    _record_heartbeat(
        conn,
        object_key,
        OUTCOME_INDEXED,
        success=True,
        detail={"source_version_id": version_id, "embed_calls": report.embed_calls},
    )
    conn.commit()
    return WatcherReport(
        outcome=OUTCOME_INDEXED,
        source_version_id=version_id,
        embed_calls=report.embed_calls,
    )


def _refresh_fingerprint(conn: psycopg.Connection, object_key: str, fingerprint: str) -> None:
    """RFC-0019 6 fila 1: el contenido no cambio, solo el `mtime`. La fila
    vigente se queda donde esta y solo se le renueva la huella."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE source_documents SET source_fingerprint = %s, updated_at = now() "
            "WHERE object_key = %s AND is_current",
            (fingerprint, object_key),
        )


def _register_version(
    conn: psycopg.Connection,
    object_key: str,
    version_id: str,
    observed_fingerprint: str,
    content_sha256: str,
    metadata: dict[str, Any],
) -> str:
    """Paso 5 -- RFC-0019 3. Entra como 'discovered'; solo la promocion la
    marca 'indexed', que es lo que ck_source_current exige para is_current."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO source_documents "
            "(object_key, source_version_id, source_fingerprint, content_sha256, "
            " source_metadata, ingestion_status) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, 'discovered') RETURNING id",
            (object_key, version_id, observed_fingerprint, content_sha256, json.dumps(metadata)),
        )
        row = cur.fetchone()

    if row is None:  # pragma: no cover -- INSERT ... RETURNING siempre devuelve
        raise RuntimeError("el registro de la version no devolvio id")
    return str(row[0])


def _create_job(
    conn: psycopg.Connection, object_key: str, version_id: str, source_document_id: str
) -> None:
    """Paso 6 -- RFC-0019 3. El ON CONFLICT es el que absorbe una ejecucion
    que muriera despues del paso 5: el idempotency_key es determinista a
    partir de object_key y del token de version (A-10)."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_jobs "
            "(idempotency_key, object_key, source_version_id, source_document_id) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (idempotency_key) DO NOTHING",
            (f"{object_key}@{version_id}", object_key, version_id, source_document_id),
        )


def _claim_job(
    conn: psycopg.Connection, object_key: str, idempotency_key: str, lease_seconds: int
) -> str | None:
    """Paso 7a -- RFC-0019 5. Devuelve el token si reclamo, None si otra
    ejecucion sostiene un lease vivo sobre el mismo `object_key`.

    El NOT EXISTS es la exclusion mutua: mira leases VIVOS, no cualquier
    trabajo en curso. Un `lease_expires_at` en el pasado es reclamable a
    proposito -- si no lo fuera, una ejecucion que muriera a mitad dejaria el
    corpus sin indexar para siempre y nadie lo notaria salvo por el latido.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_jobs SET job_state = 'processing', "
            "  lease_token = gen_random_uuid(), "
            "  lease_expires_at = now() + make_interval(secs => %(lease)s), "
            "  attempt_count = attempt_count + 1, started_at = now(), updated_at = now() "
            "WHERE idempotency_key = %(idem)s "
            "  AND NOT EXISTS ( "
            "    SELECT 1 FROM ingestion_jobs AS live "
            "    WHERE live.object_key = %(key)s "
            "      AND live.job_state = 'processing' "
            "      AND live.lease_expires_at > now() "
            "      AND live.idempotency_key <> %(idem)s) "
            "RETURNING lease_token",
            {"lease": lease_seconds, "idem": idempotency_key, "key": object_key},
        )
        row = cur.fetchone()

    return None if row is None else str(row[0])


def _complete_job(conn: psycopg.Connection, idempotency_key: str) -> None:
    """El lease se SUELTA al terminar: sin esto el `object_key` quedaria
    ocupado hasta que caducara. `ck_lease` exige anular token y expiracion
    juntos, nunca uno solo."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_jobs SET job_state = 'succeeded', lease_token = NULL, "
            "  lease_expires_at = NULL, completed_at = now(), updated_at = now() "
            "WHERE idempotency_key = %s",
            (idempotency_key,),
        )


def _promote(conn: psycopg.Connection, object_key: str, version_id: str) -> None:
    """Paso 8 -- RFC-0019 6.1, en UNA transaccion y en este orden.

    ck_source_current prohibe marcar vigente una version que no este
    'indexed'; idx_source_one_current prohibe dos vigentes a la vez. Hacerlo
    en dos transacciones abriria un instante sin version vigente, y el paso 2
    del ciclo siguiente no encontraria contra que comparar.
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE source_documents SET ingestion_status = 'superseded', "
            "is_current = false, updated_at = now() "
            "WHERE object_key = %s AND is_current",
            (object_key,),
        )
        cur.execute(
            "UPDATE source_documents SET ingestion_status = 'indexed', "
            "indexed_at = now(), updated_at = now() "
            "WHERE object_key = %s AND source_version_id = %s",
            (object_key, version_id),
        )
        cur.execute(
            "UPDATE source_documents SET is_current = true, updated_at = now() "
            "WHERE object_key = %s AND source_version_id = %s",
            (object_key, version_id),
        )


async def _run_cli(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_run_cli()))
