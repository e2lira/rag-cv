"""Construccion del agente -- RFC-0004 6.

build_agent() no menciona ningun proveedor concreto (invariante I-9, A-6b):
recibe el modelo ya construido por build_model() y nunca ve una credencial
(A-11, RFC-0004 6.1) -- eso lo resuelve build_model segun PROVEEDOR
(RFC-0013 5).
"""

from strands import Agent

from app.core.settings import Settings
from app.providers.llm import build_model


def build_agent(settings: Settings, persona: str) -> Agent:
    build_model(settings)  # referencia real -- ver RFC-0004 6, cuerpo pendiente de su ciclo
    raise NotImplementedError
