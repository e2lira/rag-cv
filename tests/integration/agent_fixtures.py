"""Dobles de prueba para el agente -- RFC-0004 12.

Ninguna prueba automatica de este RFC llama a una API de pago (ADR-0012):
ScriptedModel dobla al modelo con un guion fijo de eventos, y las factorias
de espia doblan las herramientas manteniendo su firma real (lo que el
modelo lee para decidir), registrando cuantas veces y con que argumentos
se llamaron.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import psycopg
from strands import tool
from strands.models.model import Model
from strands.types.tools import ToolContext


def crear_conversacion(conn: psycopg.Connection, *, key_id: str = "test") -> str:
    """Inserta una fila de conversations y devuelve su id -- RFC-0004 7
    trata la creacion de la conversacion como responsabilidad de RFC-0005;
    las pruebas de memoria la resuelven directamente por SQL."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO conversations (key_id) VALUES (%s) RETURNING id", (key_id,))
        (conversation_id,) = cur.fetchone()
    conn.commit()
    return str(conversation_id)


def texto(mensaje: str) -> list[dict[str, Any]]:
    """Un turno del modelo que responde solo con texto (sin tool_use)."""
    return [
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": mensaje}}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]


def llamada_herramienta(
    tool_use_id: str, nombre: str, entrada: dict[str, Any]
) -> list[dict[str, Any]]:
    """Un turno del modelo que pide UNA llamada a herramienta."""
    delta_entrada = {"toolUse": {"input": json.dumps(entrada)}}
    return [
        {"messageStart": {"role": "assistant"}},
        {
            "contentBlockStart": {
                "contentBlockIndex": 0,
                "start": {"toolUse": {"toolUseId": tool_use_id, "name": nombre}},
            }
        },
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": delta_entrada}},
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "tool_use"}},
    ]


class ScriptedModel(Model):
    """RFC-0004 12: cada llamada a stream() consume el siguiente turno del
    guion, en orden. Agotar el guion es un error de la prueba (el agente
    llamo al modelo mas veces de las previstas), no un fallo silencioso."""

    def __init__(self, script: list[list[dict[str, Any]]]) -> None:
        self._script = list(script)
        self.stream_calls: list[dict[str, Any]] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> Any:
        return {}

    async def structured_output(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise NotImplementedError
        yield  # pragma: no cover -- mantiene la firma de generador asincrono

    async def stream(
        self,
        messages: Any,
        tool_specs: Any = None,
        system_prompt: Any = None,
        *,
        tool_choice: Any = None,
        system_prompt_content: Any = None,
        invocation_state: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.stream_calls.append({"messages": messages, "tool_specs": tool_specs})
        if not self._script:
            raise AssertionError(
                "ScriptedModel: guion agotado -- el agente llamo al modelo mas "
                "veces de las previstas por la prueba"
            )
        turno = self._script.pop(0)
        for evento in turno:
            yield evento


SOURCES_KEY = "rfc0004_sources"


def make_search_cv_spy(
    respuesta: str = "<contexto_cv></contexto_cv>",
    fuentes: list[dict[str, Any]] | None = None,
):
    """Doble de search_cv (RFC-0004 5.1): misma firma, sin base de datos.

    Escribe en invocation_state[SOURCES_KEY] igual que hara la implementacion
    real -- es el canal por el que el streaming (9) arma el evento sources
    sin tener que re-parsear el bloque <contexto_cv> de vuelta a chunks.
    """
    llamadas: list[dict[str, Any]] = []

    @tool(context=True)
    async def search_cv(
        query: str, tool_context: ToolContext, chunk_types: list[str] | None = None
    ) -> str:
        """Busca en el CV de la persona y devuelve los fragmentos más relevantes.

        Args:
            query: La pregunta o los términos a buscar, en lenguaje natural.
            chunk_types: Filtro opcional. Valores válidos: "experiencia", "proyecto",
                "habilidad", "educacion", "faq", "perfil". Úsalo solo si la pregunta
                se limita claramente a una de esas categorías.

        Returns:
            Un bloque <contexto_cv> con los fragmentos relevantes, o un aviso de que
            no se encontró información.
        """
        llamadas.append({"query": query, "chunk_types": chunk_types})
        if fuentes:
            tool_context.invocation_state.setdefault(SOURCES_KEY, []).extend(fuentes)
        return respuesta

    search_cv.calls = llamadas  # type: ignore[attr-defined]
    return search_cv


def make_failing_search_cv_spy(excepcion: Exception):
    """Doble de search_cv que siempre falla -- RFC-0004 10: para probar que
    el fallo corta el turno en vez de llegar al modelo como texto."""

    @tool
    async def search_cv(query: str, chunk_types: list[str] | None = None) -> str:
        """Busca en el CV de la persona y devuelve los fragmentos más relevantes.

        Args:
            query: La pregunta o los términos a buscar, en lenguaje natural.
            chunk_types: Filtro opcional. Valores válidos: "experiencia", "proyecto",
                "habilidad", "educacion", "faq", "perfil". Úsalo solo si la pregunta
                se limita claramente a una de esas categorías.

        Returns:
            Un bloque <contexto_cv> con los fragmentos relevantes, o un aviso de que
            no se encontró información.
        """
        raise excepcion

    return search_cv


def make_list_cv_sections_spy(respuesta: str = "indice vacio"):
    """Doble de list_cv_sections (RFC-0004 5.2): misma firma, sin base de datos."""
    llamadas: list[dict[str, Any]] = []

    @tool
    async def list_cv_sections() -> str:
        """Devuelve el índice del CV: secciones, empresas, puestos y rangos de fechas."""
        llamadas.append({})
        return respuesta

    list_cv_sections.calls = llamadas  # type: ignore[attr-defined]
    return list_cv_sections
