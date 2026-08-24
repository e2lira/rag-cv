"""RFC-0013 CA-1, CA-2, CA-11: build_model construye el proveedor correcto
segun PROVEEDOR, rechaza un valor desconocido, y mantiene streaming activo.

Los tres criterios comparten una sola unidad de implementacion -- revertir
build_model a un cuerpo vacio los pone en rojo a los tres a la vez (RFC-0014
6.1.1) -- asi que van en el mismo par rojo/verde.

Sin red ni clave real (RFC-0013 12): los tres proveedores se doblan en el
punto exacto donde build_model los construye, nunca se instancia un cliente
real."""

from unittest.mock import MagicMock, patch

import pytest
from strands.models import ModelRouter
from strands.models.model import Model

from app.core.settings import Settings
from app.providers.fallback import AvailabilityFallbackStrategy
from app.providers.llm import build_model

pytestmark = pytest.mark.unit


def _configure(monkeypatch: pytest.MonkeyPatch, proveedor: str, **extra: str) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL_ID", raising=False)
    monkeypatch.setenv("PROVEEDOR", proveedor)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def test_build_model_bedrock(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(
        monkeypatch,
        "bedrock",
        AWS_REGION="us-east-2",
        BEDROCK_MODEL_ID="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    )
    settings = Settings(_env_file=None)

    with patch("strands.models.BedrockModel") as MockBedrock:
        instance = MagicMock()
        MockBedrock.return_value = instance

        result = build_model(settings)

    assert result is instance
    _, kwargs = MockBedrock.call_args
    assert kwargs["model_id"] == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert kwargs["region_name"] == "us-east-2"
    assert kwargs["streaming"] is True


def test_build_model_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch, "anthropic", ANTHROPIC_API_KEY="sk-ant-test")
    settings = Settings(_env_file=None)

    with patch("strands.models.anthropic.AnthropicModel") as MockAnthropic:
        instance = MagicMock()
        MockAnthropic.return_value = instance

        result = build_model(settings)

    assert result is instance
    _, kwargs = MockAnthropic.call_args
    assert kwargs["model_id"] == "claude-haiku-4-5-20251001"
    assert kwargs["client_args"] == {"api_key": "sk-ant-test"}


def test_build_model_openai_compatible(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(
        monkeypatch,
        "openai_compatible",
        OPENAI_COMPATIBLE_API_KEY="sk-deepseek-test",
        OPENAI_COMPATIBLE_BASE_URL="https://api.deepseek.com",
        OPENAI_COMPATIBLE_MODEL_ID="deepseek-chat",
    )
    settings = Settings(_env_file=None)

    with patch("strands.models.openai.OpenAIModel") as MockOpenAI:
        instance = MagicMock()
        MockOpenAI.return_value = instance

        result = build_model(settings)

    assert result is instance
    _, kwargs = MockOpenAI.call_args
    assert kwargs["model_id"] == "deepseek-chat"
    assert kwargs["client_args"] == {
        "api_key": "sk-deepseek-test",
        "base_url": "https://api.deepseek.com",
    }
    assert kwargs["stream"] is True


def test_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """CA-2: PROVEEDOR desconocido lanza ValueError con los valores validos.

    Settings no rechaza un PROVEEDOR desconocido (su validador solo exige
    variables de una rama reconocida, RFC-0013 4) -- ese rechazo es trabajo
    de build_model (RFC-0013 9)."""
    _configure(monkeypatch, "azure_foundry")
    settings = Settings(_env_file=None)

    with pytest.raises(ValueError, match="azure_foundry"):
        build_model(settings)


def _modelo_falso() -> MagicMock:
    """MagicMock(spec=Model): ModelRouter valida isinstance(candidato,
    Model) y lee candidato.stateful (property real de Model) para
    rechazar modelos con estado -- un MagicMock() liso falla ambas
    comprobaciones, spec=Model pasa la primera y stateful se fija en
    False a mano porque una property mockeada es truthy por defecto."""
    modelo = MagicMock(spec=Model)
    modelo.stateful = False
    return modelo


def test_fallback_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0013 CA-8 (apagado por defecto) / RFC-0018 CA-8: sin
    PROVEEDOR_FALLBACK, build_model devuelve el modelo primario
    directamente -- nunca envuelto en un ModelRouter."""
    _configure(monkeypatch, "anthropic", ANTHROPIC_API_KEY="sk-ant-test")
    monkeypatch.delenv("PROVEEDOR_FALLBACK", raising=False)
    settings = Settings(_env_file=None)

    with patch("strands.models.anthropic.AnthropicModel") as MockAnthropic:
        instance = _modelo_falso()
        MockAnthropic.return_value = instance

        result = build_model(settings)

    assert result is instance
    assert type(result).__name__ != "ModelRouter"


def test_fallback_wraps_in_model_router_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0013 CA-8: con PROVEEDOR_FALLBACK configurado, build_model
    envuelve el primario y el secundario en un ModelRouter con
    AvailabilityFallbackStrategy -- no un FallbackModel bespoke (desviacion
    de RFC-0013 6.1 declarada en el Informe: el framework ya trae
    ModelRouter, ver app/providers/fallback.py)."""
    _configure(
        monkeypatch,
        "anthropic",
        ANTHROPIC_API_KEY="sk-ant-test",
        PROVEEDOR_FALLBACK="bedrock",
        AWS_REGION="us-east-2",
        BEDROCK_MODEL_ID="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    )
    settings = Settings(_env_file=None)

    with (
        patch("strands.models.anthropic.AnthropicModel") as MockAnthropic,
        patch("strands.models.BedrockModel") as MockBedrock,
    ):
        MockAnthropic.return_value = _modelo_falso()
        MockBedrock.return_value = _modelo_falso()

        result = build_model(settings)

    assert isinstance(result, ModelRouter)
    nombres = {c.name for c in result.candidates}
    assert nombres == {"anthropic", "bedrock"}
    assert isinstance(result._strategy, AvailabilityFallbackStrategy)


def test_anthropic_has_no_streaming_flag_to_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """CA-11, matiz sobre la rama anthropic: AnthropicConfig (strands
    1.53.0) no tiene ningun campo de streaming -- ni `streaming` ni
    `stream` -- a diferencia de BedrockConfig y OpenAIConfig. No es una
    omision del RFC que corregir con un parametro inventado: el cliente de
    Anthropic siempre transmite, sin flag que desactivarlo. Esta prueba
    documenta el hueco verificando que build_model no intenta pasar un
    kwarg que la clase no reconoce."""
    _configure(monkeypatch, "anthropic", ANTHROPIC_API_KEY="sk-ant-test")
    settings = Settings(_env_file=None)

    with patch("strands.models.anthropic.AnthropicModel") as MockAnthropic:
        instance = MagicMock()
        MockAnthropic.return_value = instance

        build_model(settings)

    _, kwargs = MockAnthropic.call_args
    assert "streaming" not in kwargs
    assert "stream" not in kwargs
