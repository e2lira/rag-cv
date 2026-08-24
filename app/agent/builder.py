"""Construccion del agente -- RFC-0004 6.

build_agent() no menciona ningun proveedor concreto (invariante I-9, A-6b):
recibe el modelo ya construido por build_model() y nunca ve una credencial
(A-11, RFC-0004 6.1) -- eso lo resuelve build_model segun PROVEEDOR
(RFC-0013 5).
"""

from strands import Agent

from app.agent.hooks import ToolCallCapHook, ToolErrorPropagationHook, ToolStreamMarkersHook
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import list_cv_sections, search_cv
from app.core.settings import Settings
from app.providers.llm import build_model


def build_agent(settings: Settings, persona: str) -> Agent:
    return Agent(
        model=build_model(settings),
        tools=[search_cv, list_cv_sections],
        system_prompt=SYSTEM_PROMPT.format(persona=persona),
        hooks=[ToolCallCapHook(), ToolErrorPropagationHook(), ToolStreamMarkersHook()],
    )
