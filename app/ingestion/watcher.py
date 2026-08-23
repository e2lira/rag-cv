"""Sondeo del corpus en el VPS -- RFC-0019 3.

Punto de entrada `python -m app.ingestion.watcher`, invocado por el cron que
instala RFC-0020 7. Cada ejecucion es un ciclo completo con salida temprana:
la inmensa mayoria termina en un `stat` y una consulta indexada.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

from app.core.settings import Settings
from app.retrieval.embedder import Embedder

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

    raise NotImplementedError


async def _run_cli(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_run_cli()))
