"""Construccion del agente -- RFC-0004 6, enmendado por ADR-0017.

build_agent() no menciona ningun proveedor concreto (invariante I-9, A-6b):
recibe el modelo ya construido por build_model() y nunca ve una credencial
(A-11, RFC-0004 6.1) -- eso lo resuelve build_model segun PROVEEDOR
(RFC-0013 5).

**El reparto de ADR-0017 vive en este modulo, y es todo el punto.** El
modelo se construye una vez por proceso; el agente, una vez por turno. La
razon no es coste -- construir el agente cuesta 1,66 ms -- sino que el
objeto `Agent` de strands acumula `self.messages` en cada invocacion: un
agente de vida larga va concatenando las conversaciones de todos los
usuarios que pasen por el, y rechaza dos invocaciones solapadas con
`ConcurrencyException`.
"""

from dataclasses import dataclass

from strands import Agent
from strands.models import ModelRouter
from strands.models.model import Model
from strands.types.content import Message

from app.agent.hooks import ToolCallCapHook, ToolErrorPropagationHook, ToolStreamMarkersHook
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import list_cv_sections, search_cv
from app.core.settings import Settings
from app.providers.llm import build_model


def build_agent(settings: Settings, persona: str) -> Agent:
    """Un agente suelto, sin historial. Se conserva para quien solo necesita
    uno -- la aplicacion usa `AgentFactory` (ADR-0017)."""
    return AgentFactory.from_settings(settings, persona).for_turn()


@dataclass(frozen=True)
class AgentFactory:
    """Lo que vive por proceso, y lo que vive por turno (ADR-0017).

    Que sea un tipo con nombre y no un `lambda` en `app.state` es
    deliberado: el reparto entre "una vez por proceso" y "una vez por turno"
    es la decision que ADR-0017 corrige, y una decision asi merece estar
    escrita donde se lea, no escondida en una clausura.
    """

    # El tipo es el que devuelve `build_model`, no una version estrechada:
    # con PROVEEDOR_FALLBACK configurado es un router (RFC-0013 6.1), y
    # estrechar aqui obligaria a un cast que solo taparia el caso.
    model: Model | ModelRouter
    persona: str

    @classmethod
    def from_settings(cls, settings: Settings, persona: str) -> "AgentFactory":
        """Construye el modelo -- **esto es lo caro y lo que va en el lifespan**.

        `build_model` resuelve credenciales y cliente del proveedor. No llama
        a la API (ADR-0012): instancia.
        """
        return cls(model=build_model(settings), persona=persona)

    def for_turn(self, messages: list[Message] | None = None) -> Agent:
        """Un agente para **este** turno, con su historial precargado.

        `messages` es el historial de ESA conversacion (RFC-0004 7). Se copia
        con `list(...)` porque strands escribe sobre la lista que recibe: sin
        la copia, el turno mutaria el historial que le paso quien lo llamo.
        """
        return Agent(
            model=self.model,
            messages=list(messages or []),
            tools=[search_cv, list_cv_sections],
            system_prompt=SYSTEM_PROMPT.format(persona=self.persona),
            hooks=[ToolCallCapHook(), ToolErrorPropagationHook(), ToolStreamMarkersHook()],
        )
