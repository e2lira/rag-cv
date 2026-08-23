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
