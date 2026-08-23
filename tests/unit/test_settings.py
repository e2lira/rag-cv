"""RFC-0011 CA-0': el entorno no se declara listo si falta OPENAI_API_KEY."""

import pytest

from app.core.settings import Settings

pytestmark = pytest.mark.unit


def test_missing_openai_api_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    with pytest.raises(Exception, match="OPENAI_API_KEY"):
        Settings()
