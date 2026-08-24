"""RFC-0004 6: build_agent construye el agente con el modelo de build_model,
las dos herramientas de 5 y el prompt de persona (A-6, A-11).

Un solo par rojo/verde para las tres afirmaciones -- revertir build_agent a
un cuerpo vacio las rompe a las tres a la vez (RFC-0014 6.1.1)."""

from unittest.mock import MagicMock, patch

import pytest
from strands import Agent

from app.agent.prompts import SYSTEM_PROMPT
from app.core.settings import Settings

pytestmark = pytest.mark.unit


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.setenv("PROVEEDOR", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("ANTHROPIC_MODEL_ID", raising=False)
    return Settings(_env_file=None)


def test_build_agent_wires_model_tools_and_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch)
    modelo_falso = MagicMock()

    with patch("app.agent.builder.build_model", return_value=modelo_falso) as mock_build_model:
        from app.agent.builder import build_agent

        agent = build_agent(settings, persona="Ada Lovelace")

    mock_build_model.assert_called_once_with(settings)
    assert isinstance(agent, Agent)
    assert agent.model is modelo_falso
    # A-6: exactamente estas dos, ninguna otra -- Strands no inyecta tools
    # propias salvo context_manager="agentic" (no configurado aqui).
    assert sorted(agent.tool_names) == ["list_cv_sections", "search_cv"]
    assert agent.system_prompt == SYSTEM_PROMPT.format(persona="Ada Lovelace")
