"""Comportamiento del agente en el turno completo -- RFC-0004 11.

Los CA de esta tabla viven juntos en este modulo porque describen la misma
unidad observable (un turno del agente), aunque no todos toquen PostgreSQL:
cada funcion lleva su propia marca (`unit` o `integration`) segun si necesita
`database_url` o no -- no se declara una marca nueva (RFC-0004 12).
"""

from unittest.mock import patch

import psycopg
import pytest
from strands import Agent
from strands.types.exceptions import EventLoopException

from app.agent.hooks import ToolCallCapHook, ToolErrorPropagationHook, ToolStreamMarkersHook
from app.agent.memory import load_history, record_turn
from app.agent.prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_VERSION
from app.agent.streaming import stream_turn
from tests.integration.agent_fixtures import (
    ScriptedModel,
    crear_conversacion,
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
        hooks=[ToolCallCapHook(), ToolErrorPropagationHook(), ToolStreamMarkersHook()],
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


@pytest.mark.integration
def test_no_context_bleed(database_url: str) -> None:
    """CA-5: dos conversaciones distintas no comparten historial."""
    with psycopg.connect(database_url) as conn:
        conversacion_a = crear_conversacion(conn)
        conversacion_b = crear_conversacion(conn)
        record_turn(
            conn, conversacion_a, user_text="Hola A", assistant_text="Respuesta A", prompt_version=1
        )
        record_turn(
            conn, conversacion_b, user_text="Hola B", assistant_text="Respuesta B", prompt_version=1
        )

        historial_a = load_history(conn, conversacion_a)

    contenidos = [mensaje["content"] for mensaje in historial_a]
    assert "Hola A" in contenidos
    assert "Respuesta A" in contenidos
    assert "Hola B" not in contenidos
    assert "Respuesta B" not in contenidos


@pytest.mark.integration
def test_prompt_version_recorded(database_url: str) -> None:
    """CA-9: SYSTEM_PROMPT_VERSION se persiste en cada turno."""
    with psycopg.connect(database_url) as conn:
        conversacion = crear_conversacion(conn)
        record_turn(
            conn,
            conversacion,
            user_text="Hola",
            assistant_text="Hola, ¿en qué te ayudo?",
            prompt_version=SYSTEM_PROMPT_VERSION,
        )

        with conn.cursor() as cur:
            cur.execute(
                "SELECT prompt_version FROM messages "
                "WHERE conversation_id = %s AND role = 'assistant'",
                (conversacion,),
            )
            (version,) = cur.fetchone()

    assert version == SYSTEM_PROMPT_VERSION


@pytest.mark.integration
def test_memory_trims_oldest_turns_over_budget(database_url: str) -> None:
    """RFC-0004 7: si el historial excede token_budget se recortan los
    turnos mas antiguos primero -- rama sin CA numerado propio, pero con
    logica real (cierre de cobertura, sin cambio de comportamiento)."""
    with psycopg.connect(database_url) as conn:
        conversacion = crear_conversacion(conn)
        for i in range(5):
            record_turn(
                conn,
                conversacion,
                user_text=f"pregunta {i} " + "x" * 50,
                assistant_text=f"respuesta {i} " + "y" * 50,
                prompt_version=1,
            )

        historial_completo = load_history(conn, conversacion, max_turns=5, token_budget=10_000)
        historial_recortado = load_history(conn, conversacion, max_turns=5, token_budget=1)

    assert len(historial_recortado) < len(historial_completo)
    assert len(historial_recortado) >= 1
    assert "pregunta 0" not in historial_recortado[0]["content"]
    assert historial_recortado[-1]["content"] == historial_completo[-1]["content"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sse_sources_before_done() -> None:
    """CA-8: el flujo SSE emite sources antes de done en toda respuesta con
    busqueda -- el cliente puede mostrar la procedencia mientras el texto
    todavia se escribe (RFC-0004 9)."""
    modelo = ScriptedModel(
        [
            llamada_herramienta("t1", "search_cv", {"query": "banca"}),
            texto("Tiene experiencia en banca [F1]."),
        ]
    )
    search_cv = make_search_cv_spy(
        respuesta="<contexto_cv>[F1] banca</contexto_cv>",
        fuentes=[{"chunk_id": 42, "unit": "Banorte -- Ingeniera de Datos Senior"}],
    )
    agent = _agente_de_prueba(modelo, search_cv=search_cv)

    eventos = [evento async for evento in stream_turn(agent, "¿Tiene experiencia en banca?")]

    tipos = [e["type"] for e in eventos]
    assert "token" in tipos
    assert "tool_start" in tipos
    assert "tool_end" in tipos
    assert tipos[-1] == "done"
    assert tipos.index("sources") < tipos.index("done")

    (evento_fuentes,) = [e for e in eventos if e["type"] == "sources"]
    esperado = [{"chunk_id": 42, "unit": "Banorte -- Ingeniera de Datos Senior"}]
    assert evento_fuentes["chunks"] == esperado


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_emits_error_and_stops_on_failure() -> None:
    """RFC-0004 9: un fallo a mitad del flujo emite error y cierra el
    flujo -- no se deja colgado."""
    modelo = ScriptedModel([llamada_herramienta("t1", "search_cv", {"query": "x"})])
    search_cv = make_failing_search_cv_spy(ConnectionError("timeout de retrieval"))
    agent = _agente_de_prueba(modelo, search_cv=search_cv)

    eventos = [evento async for evento in stream_turn(agent, "¿Que hizo en su ultimo puesto?")]

    tipos = [e["type"] for e in eventos]
    assert tipos[-1] == "error"
    assert "done" not in tipos
    assert "timeout de retrieval" in eventos[-1]["message"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_iteration_cap_stops_runaway_reasoning() -> None:
    """RFC-0004 8: 4 iteraciones como maximo -- corta bucles de razonamiento
    aunque el tope de herramientas (2) solo cancele, no termine el turno."""
    # 10 turnos de tool_use: el tope de herramientas cancela desde la 3ra,
    # pero el bucle seguiria pidiendo turnos al modelo sin un limite propio
    # de iteraciones -- por eso el guion no incluye un turno final de texto.
    modelo = ScriptedModel(
        [llamada_herramienta(f"t{i}", "search_cv", {"query": f"q{i}"}) for i in range(10)]
    )
    agent = _agente_de_prueba(modelo)

    [_ async for _ in stream_turn(agent, "Dame todo lo que tengas")]

    assert len(modelo.stream_calls) <= 4


@pytest.mark.unit
@pytest.mark.asyncio
async def test_turn_timeout_cancels_and_emits_error() -> None:
    """RFC-0004 8: tiempo total del turno acotado -- cancelacion limpia,
    error con codigo que una capa superior (RFC-0005) mapea a HTTP 504."""
    modelo = ScriptedModel([texto("respuesta lenta")], demora=0.3)
    agent = _agente_de_prueba(modelo)

    eventos = [evento async for evento in stream_turn(agent, "Hola", timeout_seconds=0.05)]

    assert eventos[-1] == {"type": "error", "code": "timeout", "message": eventos[-1]["message"]}
    assert "done" not in [e["type"] for e in eventos]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_token_budget_logs_warning_when_exceeded() -> None:
    """RFC-0004 8: presupuesto de 8000 tokens de entrada, auditado y con
    alerta si se supera -- no corta el turno, solo lo registra."""
    modelo = ScriptedModel([texto("ok")])
    agent = _agente_de_prueba(modelo)
    mensaje_largo = "x " * 20_000  # ampliamente por encima de 8000 tokens aprox.

    with patch("app.agent.streaming.logger") as mock_logger:
        [_ async for _ in stream_turn(agent, mensaje_largo)]

    mock_logger.warning.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_input_token_budget_silent_when_within_range() -> None:
    modelo = ScriptedModel([texto("ok")])
    agent = _agente_de_prueba(modelo)

    with patch("app.agent.streaming.logger") as mock_logger:
        [_ async for _ in stream_turn(agent, "Hola")]

    mock_logger.warning.assert_not_called()
