# Bug: `search_cv` no escribe las fuentes en `invocation_state`

| Campo | Valor |
| :--- | :--- |
| **Severidad** | Alta (fallo silencioso: nada falla, pero la trazabilidad deja de existir) |
| **RFC dueño del contrato** | RFC-0004 §9 (evento `sources`), RFC-0005 §4 y §13 |
| **Estado** | Abierto — requiere análisis y reparación |
| **Detectado** | 2026-08-25, durante revisión manual del flujo RAG |

## 1. Resumen

La herramienta real `search_cv` (`app/agent/tools.py`) entrega el contexto recuperado al modelo
(como bloque `<contexto_cv>`), pero **no escribe las fuentes** en `invocation_state`. El evento
`sources` que `streaming.py` arma desde `invocation_state["rfc0004_sources"]` nunca dispara, y en
consecuencia `sources`, `grounded` y `annotations` salen vacíos en producción.

El síntoma es silencioso: el agente **responde bien** (el contexto sí llega), por eso ninguna
prueba ni ninguna verificación manual lo delata — la trazabilidad, que es lo único que separa a
este sistema de uno que inventa, desaparece sin un solo error en los registros.

## 2. Síntoma e impacto

Para cualquier turno que use `search_cv`:

- `/v1/chat`: `sources == []` y `grounded == false` **siempre**, aunque la respuesta esté
  fundamentada en fragmentos reales del CV (RFC-0005 §4).
- `/v1/responses`: `annotations == []` **siempre** (RFC-0005 §13.3), rompiendo CA-17 (las citas
  deben coincidir con `sources`).
- Un cliente no puede distinguir "no consta" de "sí consta" sin leer el texto — justo lo que
  `grounded` existe para resolver.
- La trazabilidad `chunk_id`/`unit` que alimenta la evaluación de `groundedness` (RFC-0009) queda
  vacía.

El contexto `<contexto_cv>` sí llega al modelo (por el valor de retorno de la herramienta), así
que la calidad de la respuesta no lo denuncia. Es el peor modo de fallo posible en un RAG.

## 3. Causa raíz (evidencia)

1. **La herramienta real no escribe las fuentes.** `app/agent/tools.py:49-68`:

   ```python
   @tool
   async def search_cv(query: str, chunk_types: list[str] | None = None) -> str:
       ...
       pool, embedder = _dependencies()
       with pool.connection() as conn:
           chunks = await hybrid_search(conn, embedder, query)
       if chunk_types:
           chunks = [c for c in chunks if c.chunk_type in chunk_types]
       return format_context_block(chunks)   # ← solo retorna texto, no registra fuentes
   ```

   No hay `@tool(context=True)` ni parámetro `tool_context: ToolContext`, por lo que la herramienta
   no tiene acceso a `invocation_state`.

2. **El lector sí espera esa clave.** `app/agent/streaming.py:20` define
   `_SOURCES_KEY = "rfc0004_sources"` y en `streaming.py:97-99`:

   ```python
   fuentes = invocation_state.get(_SOURCES_KEY)
   if fuentes:
       yield {"type": "sources", "chunks": fuentes}
   ```

   Nadie en `app/` escribe esa clave en producción (grep: solo aparece en `streaming.py`).

3. **El consumidor arma `grounded` de ese evento.** `app/services/chat.py:150-164` recolecta
   `fuentes` del evento `sources`, y `_persistir` (línea 230) hace `fundamentado = bool(fuentes)`.

4. **El doble de prueba sí lo hace bien — con tiempo futuro.** `tests/integration/agent_fixtures.py`:

   - `:106` `SOURCES_KEY = "rfc0004_sources"`
   - `:121` `@tool(context=True)` y `:122` `tool_context: ToolContext`
   - `:139` `tool_context.invocation_state.setdefault(SOURCES_KEY, []).extend(fuentes)`
   - `:115-117` el comentario: *«Escribe en invocation_state[SOURCES_KEY] **igual que hará la
     implementación real**»* — futuro. La implementación real todavía no lo hace.

## 4. Por qué no lo cubren las pruebas

`tests/integration/test_chat.py` y `tests/integration/test_responses_api.py` montan el agente con
`_FabricaDePrueba` (`test_chat.py:69-92`), que usa `make_search_cv_spy`, **no** la herramienta real.
El espía escribe las fuentes correctamente, así que `test_annotations_match_sources` (CA-17) pasa —
pero dobla justo la pieza que en producción está rota. No existe un test de integración que ejercite
`search_cv` real de punta a punta y afirme que el evento `sources` llega con los `chunk_id`.

## 5. Contrato violado

RFC-0004 §9 (reproducido en el docstring de `streaming.py:57-58`): el evento `sources` se arma *«con
lo acumulado en `invocation_state` por las herramientas (bajo `_SOURCES_KEY`), no re-parseando su
texto»*. La herramienta incumple su parte: acumular las fuentes.

## 6. Archivos implicados

| Archivo | Rol |
| :--- | :--- |
| `app/agent/tools.py` | **Sitio de la reparación**: `search_cv` debe registrar las fuentes |
| `app/agent/streaming.py` | Lee `_SOURCES_KEY` y emite el evento `sources` (sin cambios) |
| `app/services/chat.py` | Consume `sources` para `grounded` y `source_chunk_ids` (sin cambios) |
| `app/services/open_responses.py` | `annotations_from` mapea `sources` → `annotations` (sin cambios) |
| `app/retrieval/hybrid.py` | `RetrievedChunk` ya expone `id`, `unit`, `section`, `score`, `degraded` |
| `tests/integration/agent_fixtures.py` | El espía correcto que sirve de referencia para la firma |

## 7. Propuesta de reparación (para análisis)

Alinear la herramienta real con el espía de referencia:

1. Decorar con contexto: `@tool(context=True)` y añadir `tool_context: ToolContext` a la firma.
2. Tras filtrar por `chunk_types` (importante: usar **la misma lista** que se formatea, para que el
   orden de `[F1]…[Fn]` coincida con el de las fuentes), escribir:

   ```python
   tool_context.invocation_state.setdefault("rfc0004_sources", []).extend(
       {"chunk_id": c.id, "unit": c.unit, "section": c.section,
        "score": c.score, "degraded": c.degraded}
       for c in chunks
   )
   ```

   Claves mínimas que exigen los consumidores: `chunk_id` (`chat.py:239`), `unit`
   (`open_responses.py:78`), `degraded` (`chat.py:271`).

3. `list_cv_sections` **no** debe escribir fuentes: es un índice, no recuperación.

La decisión de forma final (claves exactas, si se reutiliza `SOURCES_KEY` como constante compartida
en lugar de duplicar el literal, y si `search_cv` devuelve además las fuentes por retorno) queda al
análisis del reparador.

## 8. Verificación tras la reparación

- Un test de integración que ejercite `search_cv` real (sin espía) y afirme:
  - el evento `sources` llega antes de `done`;
  - `grounded == true` cuando hay fragmentos, `false` cuando `hybrid_search` devuelve `[]`;
  - `annotations` de `/v1/responses` coincide con `sources` de `/v1/chat` (CA-17).
- `invoke test` y `invoke lint` en verde.

## 9. Referencias

- RFC-0004 §9 — vocabulario de eventos del turno y `sources`.
- RFC-0005 §4 (`sources`, `grounded`), §13.3 (`annotations`), CA-17.
- ADR-0009 / RFC-0019 — sondeo del corpus (contexto del sistema).
