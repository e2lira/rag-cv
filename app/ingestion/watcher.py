"""Sondeo del corpus en el VPS -- RFC-0019 3.

Punto de entrada `python -m app.ingestion.watcher`, invocado por el cron que
instala RFC-0020 7. Cada ejecucion es un ciclo completo con salida temprana:
la inmensa mayoria termina en un `stat` y una consulta indexada.
"""

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


def fingerprint(path: Path) -> str:
    """Huella barata del paso 1 -- RFC-0019 3: `mtime_ns-size`, sin leer."""
    raise NotImplementedError


async def run_once(
    conn: psycopg.Connection,
    embedder: Embedder,
    settings: Settings,
) -> WatcherReport:
    """Un ciclo completo del sondeo -- RFC-0019 3."""
    raise NotImplementedError


async def _run_cli(argv: list[str] | None = None) -> int:
    raise NotImplementedError


if __name__ == "__main__":  # pragma: no cover
    import asyncio

    sys.exit(asyncio.run(_run_cli()))
