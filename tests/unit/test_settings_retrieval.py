"""RFC-0003 5, 3.4: las nueve variables de la recuperacion hibrida, con los
valores por defecto del contrato.

Bloque atomico -> forma de suite completa (RFC-0014 6.1.1): las nueve llegan
en la misma edicion de Settings y revertirla las enrojece a la vez.
"""

from pathlib import Path

import pytest

from app.core.settings import Settings

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]

_VARS = (
    "RETRIEVAL_CANDIDATES",
    "RETRIEVAL_TOP_K",
    "RETRIEVAL_EF_SEARCH",
    "RRF_K",
    "RETRIEVAL_MIN_SCORE",
    "RETRIEVAL_TIMEOUT_MS",
    "RETRIEVAL_CONTEXT_BUDGET",
    "RRF_WEIGHT_SEMANTIC",
    "RRF_WEIGHT_LEXICAL",
)


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    for name in _VARS:
        monkeypatch.delenv(name, raising=False)


def test_retrieval_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Los nueve valores por defecto son los de las tablas de 5 y 3.4."""
    _base_env(monkeypatch)
    settings = Settings(_env_file=None)

    assert settings.retrieval_candidates == 20
    assert settings.retrieval_top_k == 5
    assert settings.retrieval_ef_search == 40
    assert settings.rrf_k == 60
    assert settings.retrieval_min_score == 0.016
    assert settings.retrieval_timeout_ms == 2000
    assert settings.retrieval_context_budget == 2500
    assert settings.rrf_weight_semantic == 1.0
    assert settings.rrf_weight_lexical == 1.0


def test_retrieval_values_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """No son constantes: RRF_WEIGHT_SEMANTIC/LEXICAL son la palanca de
    ajuste que RFC-0003 3.4 declara mas barata cuando la evaluacion muestra
    sesgo hacia una rama."""
    _base_env(monkeypatch)
    monkeypatch.setenv("RETRIEVAL_CANDIDATES", "30")
    monkeypatch.setenv("RETRIEVAL_TOP_K", "8")
    monkeypatch.setenv("RETRIEVAL_EF_SEARCH", "80")
    monkeypatch.setenv("RRF_K", "10")
    monkeypatch.setenv("RETRIEVAL_MIN_SCORE", "0.05")
    monkeypatch.setenv("RETRIEVAL_TIMEOUT_MS", "500")
    monkeypatch.setenv("RETRIEVAL_CONTEXT_BUDGET", "1000")
    monkeypatch.setenv("RRF_WEIGHT_SEMANTIC", "1.5")
    monkeypatch.setenv("RRF_WEIGHT_LEXICAL", "0.5")

    settings = Settings(_env_file=None)

    assert settings.retrieval_candidates == 30
    assert settings.retrieval_top_k == 8
    assert settings.retrieval_ef_search == 80
    assert settings.rrf_k == 10
    assert settings.retrieval_min_score == 0.05
    assert settings.retrieval_timeout_ms == 500
    assert settings.retrieval_context_budget == 1000
    assert settings.rrf_weight_semantic == 1.5
    assert settings.rrf_weight_lexical == 0.5


def test_env_example_documents_every_retrieval_variable() -> None:
    """ADU-PROCESO 5: toda variable nueva va a .env.example."""
    env_example = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    missing = [name for name in _VARS if f"{name}=" not in env_example]

    assert not missing, f".env.example no documenta: {missing}"
