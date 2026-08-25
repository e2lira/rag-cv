"""RFC-0004 6 y RFC-0005 4: el agente se construye UNA vez, en el `lifespan`.

Que exista `app.state.agent` no es un detalle de cableado: `/v1/chat` lo usa
en cada turno, y hoy solo lo rellenan las pruebas. Un despliegue real
respondería `500` en la primera pregunta.

Construirlo una vez por proceso —y no por peticion— es lo que RFC-0004 6
exige, y por una razon que no es rendimiento: el estado conversacional viaja
como historial en cada invocacion (RFC-0004 7), nunca dentro del objeto
agente. Un agente por peticion invitaria a guardarlo dentro, que es la fuga
de contexto entre usuarios mas cara de esta arquitectura.
"""

from typing import Any

import pytest

import app.main as main_module
from app.ingestion.corpus_parser import parse_front_matter
from tests.unit.test_startup_wiring import FakePool, patch_successful_startup

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_lifespan_builds_the_agent_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0004 6: al terminar el arranque hay un agente listo, y se
    construyo una sola vez."""
    calls: list[str] = []
    construcciones: list[dict[str, Any]] = []
    centinela = object()

    def _build_agent(settings: Any, persona: str) -> Any:
        construcciones.append({"persona": persona})
        return centinela

    patch_successful_startup(monkeypatch, calls, pool=FakePool())
    monkeypatch.setattr(main_module, "build_agent", _build_agent, raising=False)

    async with main_module.lifespan(main_module.app):
        assert main_module.app.state.agent is centinela

    assert len(construcciones) == 1, "el agente se construyo mas de una vez"


@pytest.mark.asyncio
async def test_the_persona_comes_from_the_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0004 4: `{persona}` sale del front-matter del corpus, no de una
    constante en el codigo -- el prompt no se duplica por persona.

    Se compara contra el corpus real leido en la prueba: si se fijara el
    nombre aqui, cambiar el corpus dejaria el prompt hablando de otra
    persona sin que nada fallara.
    """
    calls: list[str] = []
    construcciones: list[dict[str, Any]] = []

    def _build_agent(settings: Any, persona: str) -> Any:
        construcciones.append({"persona": persona})
        return object()

    patch_successful_startup(monkeypatch, calls, pool=FakePool())
    monkeypatch.setattr(main_module, "build_agent", _build_agent, raising=False)

    async with main_module.lifespan(main_module.app):
        pass

    esperada = parse_front_matter(main_module.Settings().corpus_path.read_text(encoding="utf-8"))
    assert construcciones[0]["persona"] == esperada["persona"]
