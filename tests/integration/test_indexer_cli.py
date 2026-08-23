"""RFC-0002 8: la CLI de punta a punta -- Settings, build_pool, build_embedder
y _run_cli reales, contra una base efimera. EMBEDDER=fake, nunca la API real
(ADR-0012)."""

from pathlib import Path

import pytest

from app.ingestion.indexer import _run_cli
from tests.unit.ingestion_fixtures import VALID_CORPUS

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_cli_indexes_the_corpus(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(VALID_CORPUS, encoding="utf-8")

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("EMBEDDER", "fake")

    exit_code = await _run_cli(["--corpus", str(corpus_path)])

    assert exit_code == 0


@pytest.mark.asyncio
async def test_cli_exits_2_on_invalid_corpus(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RFC-0002 9: el validador aborta antes de tocar la BD, codigo de
    salida 2."""
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(VALID_CORPUS.replace("# Perfil", "### Perfil"), encoding="utf-8")

    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("EMBEDDER", "fake")

    exit_code = await _run_cli(["--corpus", str(corpus_path)])

    assert exit_code == 2
