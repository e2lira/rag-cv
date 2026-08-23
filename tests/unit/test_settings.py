"""RFC-0011 CA-0': el entorno no se declara listo si falta OPENAI_API_KEY.

Hermetico a proposito: Settings() lee .env directamente (env_file en su
model_config), no solo os.environ, asi que monkeypatch por si solo no basta
para simular "la variable no esta" -- hay que decirle a Settings que ignore
el .env real de esta maquina. Sin esto, el resultado depende de si .env
tiene o no la clave, que es justo lo que un test hermetico no debe hacer.
"""

import pytest

from app.core.settings import Settings

pytestmark = pytest.mark.unit


def test_missing_openai_api_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")

    with pytest.raises(Exception, match="OPENAI_API_KEY"):
        Settings(_env_file=None)


def test_blank_openai_api_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una clave presente pero vacia es la forma habitual de que un
    despliegue arranque a medias en vez de fallar de inmediato (RFC-0016
    #7); no basta con comprobar que la variable existe."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")

    with pytest.raises(Exception, match="OPENAI_API_KEY"):
        Settings(_env_file=None)
