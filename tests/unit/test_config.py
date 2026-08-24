"""RFC-0017 CA-8: EMBEDDER=openai sin OPENAI_API_KEY impide el arranque.

Ya es cierto sin cambios: RFC-0011 CA-0' exige OPENAI_API_KEY de forma
incondicional (app/core/settings.py), y hoy `openai` es el unico embedder
real -- los demas estan diferidos (RFC-0017 CA-1). Este test formaliza el
criterio bajo su propio nombre, sin duplicar app/core/settings.py.
"""

from pathlib import Path

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


def test_database_url_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0021 CA-3: sin DATABASE_URL, Settings() no arranca. Sin valor por
    defecto y a proposito -- una URL de base por defecto es una invitacion a
    arrancar apuntando sin querer a la base equivocada (RFC-0021 4)."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    with pytest.raises(Exception, match="DATABASE_URL"):
        Settings(_env_file=None)


def _settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")


def test_corpus_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0002 6: CORPUS_PATH tiene valor por defecto corpus/cv.md, el
    mismo que .env.example y RFC-0011 4.5 -- en QA es una ruta absoluta
    (RFC-0016 7), por eso el tipo es Path, no una constante de string."""
    monkeypatch.delenv("CORPUS_PATH", raising=False)
    _settings_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.corpus_path == Path("corpus/cv.md")


def test_corpus_path_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings_env(monkeypatch)
    monkeypatch.setenv("CORPUS_PATH", "/srv/ragcv/corpus/cv.md")

    settings = Settings(_env_file=None)

    assert settings.corpus_path == Path("/srv/ragcv/corpus/cv.md")


def test_embed_max_tokens_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0002 6 / RFC-0012 6: EMBED_MAX_TOKENS por defecto 1800 -- el tope
    por fragmento antes de embeber, para no truncar en silencio."""
    monkeypatch.delenv("EMBED_MAX_TOKENS", raising=False)
    _settings_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.embed_max_tokens == 1800


@pytest.mark.parametrize(
    ("proveedor", "env_faltante", "campo_faltante", "resto"),
    [
        (
            "bedrock",
            "AWS_REGION",
            "aws_region",
            {"BEDROCK_MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0"},
        ),
        ("bedrock", "BEDROCK_MODEL_ID", "bedrock_model_id", {"AWS_REGION": "us-east-2"}),
        ("anthropic", "ANTHROPIC_API_KEY", "anthropic_api_key", {}),
        (
            "anthropic",
            "ANTHROPIC_MODEL_ID",
            "anthropic_model_id",
            {"ANTHROPIC_API_KEY": "sk-ant-test"},
        ),
        (
            "openai_compatible",
            "OPENAI_COMPATIBLE_API_KEY",
            "openai_compatible_api_key",
            {
                "OPENAI_COMPATIBLE_BASE_URL": "https://api.deepseek.com",
                "OPENAI_COMPATIBLE_MODEL_ID": "deepseek-chat",
            },
        ),
        (
            "openai_compatible",
            "OPENAI_COMPATIBLE_BASE_URL",
            "openai_compatible_base_url",
            {"OPENAI_COMPATIBLE_API_KEY": "sk-test", "OPENAI_COMPATIBLE_MODEL_ID": "deepseek-chat"},
        ),
        (
            "openai_compatible",
            "OPENAI_COMPATIBLE_MODEL_ID",
            "openai_compatible_model_id",
            {
                "OPENAI_COMPATIBLE_API_KEY": "sk-test",
                "OPENAI_COMPATIBLE_BASE_URL": "https://api.deepseek.com",
            },
        ),
    ],
)
def test_provider_required_vars(
    monkeypatch: pytest.MonkeyPatch,
    proveedor: str,
    env_faltante: str,
    campo_faltante: str,
    resto: dict[str, str],
) -> None:
    """RFC-0013 CA-3 / RFC-0018 CA-2: falta una variable de la rama activa de
    PROVEEDOR => Settings() no arranca, nombrando el campo que falta.

    RFC-0013 4 nombra el campo (snake_case) en el mensaje, no el alias de
    entorno -- ``', '.join(faltantes)`` sobre las claves del propio
    diccionario ``requeridas``. ANTHROPIC_MODEL_ID tiene valor por defecto
    (RFC-0018 3), asi que el caso "anthropic sin ANTHROPIC_MODEL_ID" no
    puede fallar por esa via -- se fuerza vaciandolo explicitamente en vez
    de simplemente no fijarlo."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("PROVEEDOR", proveedor)
    if env_faltante == "ANTHROPIC_MODEL_ID":
        monkeypatch.setenv("ANTHROPIC_MODEL_ID", "")
    else:
        monkeypatch.delenv("ANTHROPIC_MODEL_ID", raising=False)
    for k, v in resto.items():
        monkeypatch.setenv(k, v)

    with pytest.raises(Exception, match=campo_faltante):
        Settings(_env_file=None)


def test_provider_defaults_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0018 3 / RFC-0011 4.5: el valor por defecto de PROVEEDOR en este
    repositorio es anthropic, no el bedrock de RFC-0013 4 -- RFC-0018 lo
    sustituye, y ambos RFC aterrizan en el mismo PR, asi que no tiene sentido
    implementar primero un valor que se reemplaza en el commit siguiente.

    delenv de PROVEEDOR y ANTHROPIC_MODEL_ID, no solo el primero: un .env
    real de DEV puede fijar ANTHROPIC_MODEL_ID, y tests/conftest.py llama
    load_dotenv() a nivel de modulo -- se filtra a os.environ incluso con
    _env_file=None, que solo desactiva la lectura propia de
    pydantic-settings. Sin aislar los dos, esta prueba pasa o falla segun
    el .env de quien la corra, no segun el valor por defecto real."""
    monkeypatch.delenv("PROVEEDOR", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL_ID", raising=False)
    _settings_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.proveedor == "anthropic"
    assert settings.anthropic_model_id == "claude-haiku-4-5-20251001"


@pytest.mark.parametrize(
    ("variable", "valor_excedido"),
    [("LLM_TEMPERATURE", "1.0"), ("LLM_MAX_TOKENS", "2048")],
)
def test_inference_params_cannot_exceed_rfc0004_limits(
    monkeypatch: pytest.MonkeyPatch, variable: str, valor_excedido: str
) -> None:
    """RFC-0004 3 y A-8: `temperature <= 0.3` y `max_tokens = 1024` son el
    contrato, no un valor por defecto sugerido. Sin cota superior, un
    despliegue puede excederlos por configuracion y salirse del envolvente
    de estabilidad y coste aprobado (RF-10, RNF-5) sin que nada falle.

    Se acota por arriba, no por igualdad exacta: lo que A-8 protege es
    EXCEDER el limite -- un valor menor no compromete ni la estabilidad ni
    el coste."""
    monkeypatch.delenv("PROVEEDOR", raising=False)
    _settings_env(monkeypatch)
    monkeypatch.setenv(variable, valor_excedido)

    with pytest.raises(Exception, match=variable.lower()):
        Settings(_env_file=None)
