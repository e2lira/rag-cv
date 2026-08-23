"""RFC-0017 CA-1: la fabrica acepta EMBEDDER=openai y devuelve OpenAIEmbedder;
un valor desconocido aborta con la lista de validos, y las tres ramas
diferidas abortan diciendolo -- no con un NotImplementedError desnudo."""

import httpx2
import pytest

from app.core.settings import Settings
from app.retrieval.embedder import DeferredEmbedderError, build_embedder

pytestmark = pytest.mark.unit


def _settings(embedder: str) -> Settings:
    return Settings(
        _env_file=None,
        OPENAI_API_KEY="sk-test",
        ANTHROPIC_API_KEY="sk-ant-test",
        DATABASE_URL="postgresql://test/test",
        EMBEDDER=embedder,
    )


@pytest.fixture
def http() -> httpx2.AsyncClient:
    return httpx2.AsyncClient()


def test_openai_branch_returns_openai_embedder(http: httpx2.AsyncClient) -> None:
    from app.retrieval.embedder_openai import OpenAIEmbedder

    embedder = build_embedder(_settings("openai"), http)

    assert isinstance(embedder, OpenAIEmbedder)


# Reauditoria de PR #35: esta rama llego originalmente sin rojo real
# (5672db9 sobre 207b6bd, ya implementado). Rehecho como par TDD trazable:
# b5f13ad (regresion deliberada, rojo real en CI) -> aad60ad (verde).
def test_fake_branch_returns_fake_embedder(http: httpx2.AsyncClient) -> None:
    from app.retrieval.embedder_fake import FakeEmbedder

    embedder = build_embedder(_settings("fake"), http)

    assert isinstance(embedder, FakeEmbedder)


@pytest.mark.parametrize("deferred", ["titan", "nomic_api", "ollama"])
def test_deferred_branches_abort_explicitly(deferred: str, http: httpx2.AsyncClient) -> None:
    with pytest.raises(DeferredEmbedderError, match="diferid"):
        build_embedder(_settings(deferred), http)


def test_unknown_branch_aborts_with_valid_list(http: httpx2.AsyncClient) -> None:
    with pytest.raises(ValueError, match="openai") as exc_info:
        build_embedder(_settings("bedrock-titan-v3"), http)

    message = str(exc_info.value)
    assert "titan" in message
    assert "fake" in message
    assert "nomic_api" in message
    assert "ollama" in message
