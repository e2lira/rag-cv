"""RFC-0019 7: la CLI que invoca el cron, de punta a punta.

`python -m app.ingestion.watcher` con Settings, build_pool y build_embedder
reales contra una base efimera. EMBEDDER=fake, nunca la API real (ADR-0012).

Sin esta entrada el contrato del cron de 7 no se puede cumplir: el crontab
que instala RFC-0020 invoca exactamente este modulo.
"""

from pathlib import Path

import psycopg
import pytest

from app.ingestion.watcher import _run_cli
from tests.unit.ingestion_fixtures import VALID_CORPUS

pytestmark = pytest.mark.integration


def _env(monkeypatch: pytest.MonkeyPatch, database_url: str, corpus_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("EMBEDDER", "fake")
    monkeypatch.setenv("CORPUS_PATH", str(corpus_path))
    monkeypatch.setenv("WATCHER_STABILITY_DELAY_SECONDS", "0")


@pytest.mark.asyncio
async def test_cli_indexes_a_changed_corpus(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(VALID_CORPUS, encoding="utf-8")
    _env(monkeypatch, database_url, corpus_path)

    exit_code = await _run_cli([])

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM cv_chunks")
        chunks = cur.fetchone()

    assert exit_code == 0
    assert chunks is not None
    assert chunks[0] > 0, "la CLI no dejo el corpus indexado"


@pytest.mark.asyncio
async def test_cli_is_idempotent_across_runs(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El cron dispara cada 5 minutos: la segunda ejecucion no puede volver a
    indexar ni fallar. Es el caso habitual, no el excepcional."""
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(VALID_CORPUS, encoding="utf-8")
    _env(monkeypatch, database_url, corpus_path)

    assert await _run_cli([]) == 0
    assert await _run_cli([]) == 0

    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM source_documents")
        versions = cur.fetchone()
        cur.execute("SELECT last_outcome FROM watcher_heartbeat")
        beat = cur.fetchone()

    assert versions is not None
    assert versions[0] == 1, "un ciclo sin cambios registro version nueva"
    assert beat is not None
    assert beat[0] == "no_change"


@pytest.mark.asyncio
async def test_cli_exits_nonzero_when_the_corpus_is_missing(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RFC-0019 9: un corpus ausente es incidente. El codigo de salida lo dice
    para que quede en la bitacora del cron, no solo en el latido."""
    corpus_path = tmp_path / "no-existe.md"
    _env(monkeypatch, database_url, corpus_path)

    exit_code = await _run_cli([])

    assert exit_code != 0
