"""ADR-0017: qué se construye por proceso y qué por turno.

RFC-0004 §6 decía «el agente se construye una vez por proceso» y lo
justificaba con «el estado conversacional no se guarda en el objeto agente».
Con `strands-agents 1.53` la regla producía justo lo que la razón quería
evitar: el `Agent` acumula `self.messages`, así que uno de vida larga
concatena las conversaciones de todos los usuarios.

ADR-0017 conserva el fin y corrige el medio: **el modelo** se construye una
vez por proceso; **el agente**, una vez por turno.
"""

from typing import Any

import pytest

import app.main as main_module
from app.agent.builder import AgentFactory
from app.ingestion.corpus_parser import parse_front_matter
from tests.integration.agent_fixtures import ScriptedModel
from tests.unit.ingestion_fixtures import VALID_CORPUS
from tests.unit.test_startup_wiring import FakePool, patch_successful_startup

pytestmark = pytest.mark.unit


class _FabricaDoblada:
    """Un doble con la forma de `AgentFactory`, no un `object()` pelado.

    Tiene `for_turn` porque `build_agent` delega en la fabrica: sin el
    metodo, el rojo saldria por un `AttributeError` del doble y no por lo
    que el criterio afirma -- que el `lifespan` deja una fabrica en
    `app.state` (RFC-0014 3: el rojo tiene que decir algo).
    """

    def for_turn(self, messages: Any = None) -> Any:
        return object()


@pytest.mark.asyncio
async def test_lifespan_builds_the_factory_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0017: al terminar el arranque hay una **fábrica** lista, y el
    modelo se construyó una sola vez.

    Lo que no debe haber es un agente en `app.state`: si lo hubiera, sería
    de vida larga, y ahí es donde se acumulan los mensajes.
    """
    calls: list[str] = []
    construcciones: list[dict[str, Any]] = []
    centinela = _FabricaDoblada()

    def _from_settings(cls: Any, settings: Any, persona: str) -> Any:
        construcciones.append({"persona": persona})
        return centinela

    patch_successful_startup(monkeypatch, calls, pool=FakePool())
    monkeypatch.setattr(AgentFactory, "from_settings", classmethod(_from_settings), raising=False)

    async with main_module.lifespan(main_module.app):
        assert main_module.app.state.agent_factory is centinela
        assert not hasattr(main_module.app.state, "agent"), (
            "hay un agente de vida larga en app.state: ahí es donde se acumulan los mensajes"
        )

    assert len(construcciones) == 1, "el modelo se construyó más de una vez"


@pytest.mark.asyncio
async def test_the_persona_comes_from_the_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0004 §4: `{persona}` sale del front-matter del corpus, no de una
    constante en el código — el prompt no se duplica por persona.

    Se compara contra el corpus real leído en la prueba: si se fijara el
    nombre aquí, cambiar el corpus dejaría el prompt hablando de otra
    persona sin que nada fallara.
    """
    calls: list[str] = []
    construcciones: list[dict[str, Any]] = []

    def _from_settings(cls: Any, settings: Any, persona: str) -> Any:
        construcciones.append({"persona": persona})
        return _FabricaDoblada()

    patch_successful_startup(monkeypatch, calls, pool=FakePool())
    monkeypatch.setattr(AgentFactory, "from_settings", classmethod(_from_settings), raising=False)

    async with main_module.lifespan(main_module.app):
        pass

    # Se parsea la constante, no se relee el archivo: RFC-0014 5 exige que
    # una prueba `unit` no haga IO, y `VALID_CORPUS` es exactamente lo que
    # `corpus_de_prueba()` dejo en disco para que el arranque lo leyera.
    esperada = parse_front_matter(VALID_CORPUS)
    assert construcciones[0]["persona"] == esperada["persona"]


def test_the_factory_never_reuses_an_agent() -> None:
    """ADR-0017, el corazón: dos turnos, dos agentes distintos.

    Si la fábrica devolviera el mismo objeto, el segundo turno heredaría los
    mensajes del primero — que es exactamente el defecto que ADR-0017
    corrige, con la fábrica puesta como disfraz.
    """
    fabrica = AgentFactory(model=ScriptedModel([]), persona="Prueba")

    primero = fabrica.for_turn()
    segundo = fabrica.for_turn()

    assert primero is not segundo
    assert primero.messages is not segundo.messages


def test_the_factory_does_not_mutate_the_history_it_receives() -> None:
    """El historial que se le pasa es de quien lo cargó, no de la fábrica.

    Strands escribe sobre la lista de mensajes durante el turno. Sin copiar,
    el turno mutaría el historial de quien lo llamó — y el siguiente turno
    partiría de un historial ya contaminado por el anterior.
    """
    fabrica = AgentFactory(model=ScriptedModel([]), persona="Prueba")
    historial: list[Any] = [{"role": "user", "content": [{"text": "Turno previo"}]}]

    agente = fabrica.for_turn(historial)
    agente.messages.append({"role": "assistant", "content": [{"text": "Nuevo"}]})

    assert len(historial) == 1, "la fábrica mutó el historial que recibió"
