"""Comportamiento del agente en el turno completo -- RFC-0004 11.

Los CA de esta tabla viven juntos en este modulo porque describen la misma
unidad observable (un turno del agente), aunque no todos toquen PostgreSQL:
cada funcion lleva su propia marca (`unit` o `integration`) segun si necesita
`database_url` o no -- no se declara una marca nueva (RFC-0004 12).
"""

import pytest
from strands import Agent
from strands.types.exceptions import EventLoopException

from app.agent.hooks import ToolCallCapHook, ToolErrorPropagationHook
from app.agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION
from tests.integration.agent_fixtures import (
    ScriptedModel,
    llamada_herramienta,
    make_failing_search_cv_spy,
    make_list_cv_sections_spy,
    make_search_cv_spy,
    texto,
)

_NOMBRES_DE_PROVEEDOR = ("bedrock", "anthropic", "openai", "claude", "gpt")
_SECCIONES_REQUERIDAS = ("FUENTE DE VERDAD", "USO DE HERRAMIENTAS", "FORMA DE RESPONDER", "ALCANCE")


def _agente_de_prueba(modelo: ScriptedModel, *, search_cv=None, list_cv_sections=None) -> Agent:
    search_cv = search_cv or make_search_cv_spy()
    list_cv_sections = list_cv_sections or make_list_cv_sections_spy()
    return Agent(
        model=modelo,
        tools=[search_cv, list_cv_sections],
        system_prompt=SYSTEM_PROMPT.format(persona="Test"),
        hooks=[ToolCallCapHook(), ToolErrorPropagationHook()],
    )


@pytest.mark.unit
def test_prompt_is_provider_agnostic() -> None:
    """RFC-0013 CA-10 heredado (RFC-0004 11): un solo prompt para los tres
    proveedores -- si mencionara uno, dejaria de serlo para los otros dos."""
    contenido = SYSTEM_PROMPT.lower()
    encontrados = [nombre for nombre in _NOMBRES_DE_PROVEEDOR if nombre in contenido]
    assert not encontrados, f"el prompt de sistema menciona proveedores: {encontrados}"


@pytest.mark.unit
def test_system_prompt_has_required_sections_and_version() -> None:
    """A-3/A-4: las cuatro secciones de RFC-0004 4 sin recortes, y una
    version valida que CA-9 pueda persistir."""
    assert SYSTEM_PROMPT_VERSION >= 1
    faltantes = [s for s in _SECCIONES_REQUERIDAS if s not in SYSTEM_PROMPT]
    assert not faltantes, f"faltan secciones del prompt: {faltantes}"


@pytest.mark.unit
def test_greeting_no_tool() -> None:
    """CA-1: un saludo no dispara ninguna llamada a search_cv."""
    modelo = ScriptedModel([texto("¡Hola! ¿En qué te puedo ayudar sobre su trayectoria?")])
    search_cv = make_search_cv_spy()
    agent = _agente_de_prueba(modelo, search_cv=search_cv)

    agent("Hola")

    assert search_cv.calls == []


@pytest.mark.unit
def test_factual_one_tool_call() -> None:
    """CA-2: una pregunta factual dispara exactamente una llamada a search_cv."""
    modelo = ScriptedModel(
        [
            llamada_herramienta("t1", "search_cv", {"query": "experiencia en banca"}),
            texto("Tiene experiencia en banca [F1]."),
        ]
    )
    search_cv = make_search_cv_spy(respuesta="<contexto_cv>[F1] banca</contexto_cv>")
    agent = _agente_de_prueba(modelo, search_cv=search_cv)

    agent("¿Tiene experiencia en banca?")

    assert search_cv.calls == [{"query": "experiencia en banca", "chunk_types": None}]


@pytest.mark.unit
def test_tool_call_cap() -> None:
    """CA-3: el agente nunca hace mas de 2 llamadas a herramientas por turno,
    incluso si el modelo (falso, a proposito) sigue pidiendolas."""
    modelo = ScriptedModel(
        [
            llamada_herramienta("t1", "search_cv", {"query": "a"}),
            llamada_herramienta("t2", "search_cv", {"query": "b"}),
            llamada_herramienta("t3", "search_cv", {"query": "c"}),
            texto("No consta evidencia suficiente."),
        ]
    )
    search_cv = make_search_cv_spy()
    agent = _agente_de_prueba(modelo, search_cv=search_cv)

    agent("Dame todo lo que tengas")

    assert len(search_cv.calls) == 2


@pytest.mark.unit
def test_tool_error_propagates() -> None:
    """CA-10: ningun error de herramienta llega al modelo como texto de
    resultado -- corta el turno (RFC-0004 10, A-12)."""
    modelo = ScriptedModel([llamada_herramienta("t1", "search_cv", {"query": "x"})])
    search_cv = make_failing_search_cv_spy(ConnectionError("timeout de retrieval"))
    agent = _agente_de_prueba(modelo, search_cv=search_cv)

    # Strands envuelve cualquier excepcion que corta el bucle en
    # EventLoopException (event_loop.py), preservando la original en
    # .original_exception -- ahi es donde una capa superior (RFC-0005,
    # fuera de alcance) clasificaria por clase, no por texto (10).
    with pytest.raises(EventLoopException) as excinfo:
        agent("¿Que hizo en su ultimo puesto?")

    assert isinstance(excinfo.value.original_exception, ConnectionError)
    assert str(excinfo.value.original_exception) == "timeout de retrieval"
    # El modelo no recibio un segundo turno con el error como texto: el
    # guion (un solo elemento) no se agoto, la excepcion corto el turno.
    assert len(modelo.stream_calls) == 1
