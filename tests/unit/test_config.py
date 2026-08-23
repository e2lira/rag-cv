"""RFC-0017 CA-8: EMBEDDER=openai sin OPENAI_API_KEY impide el arranque.

Ya es cierto sin cambios: RFC-0011 CA-0' exige OPENAI_API_KEY de forma
incondicional (app/core/settings.py), y hoy `openai` es el unico embedder
real -- los demas estan diferidos (RFC-0017 CA-1). Este test formaliza el
criterio bajo su propio nombre, sin duplicar app/core/settings.py.
"""

import pytest

from app.core.settings import Settings

pytestmark = pytest.mark.unit


# Reversion verificada (RFC-0014 6.1.2, tercera evidencia): se aflojo
# temporalmente `openai_api_key` a opcional en app/core/settings.py y esta
# prueba fallo con "DID NOT RAISE Exception" -- la razon correcta, no un
# ImportError. Confirmado que prueba lo que dice; revertido antes de commitear
# (commit original del test: e8ad600).
def test_embedder_required_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("EMBEDDER", "openai")

    with pytest.raises(Exception, match="OPENAI_API_KEY"):
        Settings(_env_file=None)
