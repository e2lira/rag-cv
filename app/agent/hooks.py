"""Ganchos del agente -- RFC-0004 8: tope de llamadas a herramientas.

Strands no expone un limite de llamadas a herramientas por turno (solo
`limits={"turns": N}`, que cuenta ciclos del modelo -- RFC-0004 8, la otra
fila de la tabla). Este gancho lo implementa contando en
`invocation_state`, que Strands renueva en cada llamada a `agent()`: no
hace falta resetearlo entre turnos distintos aunque el `Agent` se reutilice
(RFC-0004 6).
"""

from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

_COUNTER_KEY = "rfc0004_tool_call_count"


class ToolCallCapHook(HookProvider):
    """Cancela cualquier llamada a herramienta que exceda max_calls dentro
    de un turno. El modelo recibe un resultado de error explicando el
    limite -- nunca se le entrega como si la herramienta hubiera fallado
    por su cuenta (10)."""

    def __init__(self, max_calls: int = 2) -> None:
        self._max_calls = max_calls

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._enforce_cap)

    def _enforce_cap(self, event: BeforeToolCallEvent) -> None:
        conteo = event.invocation_state.get(_COUNTER_KEY, 0)
        if conteo >= self._max_calls:
            event.cancel_tool = (
                f"Limite de {self._max_calls} llamadas a herramientas alcanzado "
                "para este turno; responde con la evidencia ya reunida o indica "
                "que no consta."
            )
            return
        event.invocation_state[_COUNTER_KEY] = conteo + 1
