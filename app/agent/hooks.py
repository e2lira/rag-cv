"""Ganchos del agente -- RFC-0004 8: tope de llamadas a herramientas.

Strands no expone un limite de llamadas a herramientas por turno (solo
`limits={"turns": N}`, que cuenta ciclos del modelo -- RFC-0004 8, la otra
fila de la tabla). Este gancho lo implementa contando en
`invocation_state`, que Strands renueva en cada llamada a `agent()`: no
hace falta resetearlo entre turnos distintos aunque el `Agent` se reutilice
(RFC-0004 6).
"""

from typing import Any

from strands.hooks import HookProvider, HookRegistry

_COUNTER_KEY = "rfc0004_tool_call_count"


class ToolCallCapHook(HookProvider):
    """Cancela cualquier llamada a herramienta que exceda max_calls dentro
    de un turno. El modelo recibe un resultado de error explicando el
    limite -- nunca se le entrega como si la herramienta hubiera fallado
    por su cuenta (10)."""

    def __init__(self, max_calls: int = 2) -> None:
        self._max_calls = max_calls

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        pass  # RFC-0004 8: cuerpo pendiente de su propio ciclo
