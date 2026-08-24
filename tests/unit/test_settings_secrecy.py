"""Auditoria PR #16, T-9: las claves son SecretStr y no aparecen en repr()
ni en str(). Bloqueante -- rubrica transversal, PROMPT-AUDITOR.md #3."""

import pytest

from app.core.settings import Settings

pytestmark = pytest.mark.unit


def test_repr_does_not_expose_the_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-secret-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real-secret-value")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")

    settings = Settings(_env_file=None)

    assert "sk-real-secret-value" not in repr(settings)
    assert "sk-ant-real-secret-value" not in repr(settings)
    assert "sk-real-secret-value" not in str(settings)


def test_repr_does_not_expose_the_database_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0021 CA-3 / auditoria de PR #44, B-1: a diferencia de las API
    keys, DATABASE_URL trae su credencial embebida en la propia URL
    (postgresql://usuario:password@host/db) -- el mismo criterio T-9
    aplica, aunque el campo no se llame "key"."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:SUPERSECRETA@localhost:5432/ragcv")

    settings = Settings(_env_file=None)

    assert "SUPERSECRETA" not in repr(settings)
    assert "SUPERSECRETA" not in str(settings)


def test_repr_does_not_expose_the_openai_compatible_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0013 CA-4: las tres claves de proveedor son SecretStr, no solo
    ANTHROPIC_API_KEY y OPENAI_API_KEY. openai_compatible_api_key es la
    unica de las tres que todavia no lo era (RFC-0013 3: PROVEEDOR=bedrock
    no trae una clave propia, la resuelve el rol IAM o boto_session)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PROVEEDOR", "openai_compatible")
    monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "sk-deepseek-real-secret-value")
    monkeypatch.setenv("OPENAI_COMPATIBLE_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("OPENAI_COMPATIBLE_MODEL_ID", "deepseek-chat")

    settings = Settings(_env_file=None)

    assert "sk-deepseek-real-secret-value" not in repr(settings)
    assert "sk-deepseek-real-secret-value" not in str(settings)
