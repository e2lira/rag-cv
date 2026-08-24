"""Ganchos del agente -- RFC-0004 8: tope de llamadas a herramientas.

Strands no expone un limite de llamadas a herramientas por turno (solo
`limits={"turns": N}`, que cuenta ciclos del modelo -- RFC-0004 8, la otra
fila de la tabla). Este gancho lo implementa contando en
`invocation_state`, que Strands renueva en cada llamada a `agent()`: no
hace falta resetearlo entre turnos distintos aunque el `Agent` se reutilice
(RFC-0004 6).
"""

from typing import Any

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

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


class ToolErrorPropagationHook(HookProvider):
    """RFC-0004 10, A-12: un fallo de herramienta corta el turno -- nunca
    se le entrega al modelo como texto de resultado (10, tabla). Strands,
    por defecto, atrapa la excepcion y la convierte en un ToolResult de
    error que se reenvia como si la herramienta hubiera respondido eso; el
    modelo lo leeria como dato y podria fundamentar una respuesta inventada
    (13). `HookRegistry.invoke_callbacks` propaga cualquier excepcion que
    lance un callback, asi que relanzarla aqui corta la invocacion completa
    de `agent()` en vez de alimentar el bucle."""

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(AfterToolCallEvent, self._reraise)

    def _reraise(self, event: AfterToolCallEvent) -> None:
        if event.exception is not None:
            raise event.exception


TOOL_EVENTS_KEY = "rfc0004_tool_events"


class ToolStreamMarkersHook(HookProvider):
    """RFC-0004 9: marca tool_start/tool_end para el streaming (streaming.py).

    `ToolResultEvent` no es un evento de callback (`is_callback_event =
    False`), asi que `agent.stream_async()` nunca lo entrega -- no hay otra
    forma de saber, desde fuera, cuando empieza y termina cada llamada."""

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._mark_start)
        registry.add_callback(AfterToolCallEvent, self._mark_end)

    def _mark_start(self, event: BeforeToolCallEvent) -> None:
        if event.cancel_tool:
            return  # RFC-0004 8: una llamada cancelada por el tope nunca empieza
        nombre = event.tool_use.get("name", "")
        event.invocation_state.setdefault(TOOL_EVENTS_KEY, []).append(
            {"type": "tool_start", "tool": nombre}
        )

    def _mark_end(self, event: AfterToolCallEvent) -> None:
        if event.cancel_message is not None:
            return  # simetria con _mark_start: una llamada cancelada no empezo
        nombre = event.tool_use.get("name", "")
        event.invocation_state.setdefault(TOOL_EVENTS_KEY, []).append(
            {"type": "tool_end", "tool": nombre}
        )
