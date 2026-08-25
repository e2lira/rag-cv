# ADR-0018 — Diferir el coste de turno hasta que la PoC sea operativa

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-24 |
| **Decide** | Arquitecto |
| **RFCs afectados** | RFC-0005 §4, CA-22 y A-20; RFC-0010 §4 |

## Contexto

RFC-0005 define `usage.cost_usd` a partir de una tabla productiva de precios por
`model_id`. La PoC todavía no está operativa y la tabla actual permanece vacía; por
ello los modelos conocidos devuelven `null` en vez de un coste calculado.

La prioridad explícita de esta etapa es lograr una PoC funcional. Mantener un precio
desactualizado o inventado aportaría una precisión aparente y no una métrica fiable.

## Decisión

Durante la PoC, `usage.cost_usd` puede permanecer en `null` porque no se poblará
`PRICES`. Se acepta una excepción temporal a RFC-0005 CA-22 y A-20 exclusivamente
para desbloquear la PoC.

La aritmética y el comportamiento de modelo desconocido permanecen cubiertos por
pruebas. Esta decisión no autoriza devolver `0.0` cuando el coste se desconoce.

## Alternativas consideradas

| Alternativa | A favor | En contra | Por qué se descarta |
| :--- | :--- | :--- | :--- |
| Poblar precios ahora | Cumple CA-22 de inmediato | Valores pueden quedar obsoletos antes de usar la PoC | No aporta valor a la prioridad actual |
| Devolver `0.0` | Simplifica consumidores | Declara erróneamente que el turno fue gratis | Viola el contrato semántico |
| Diferir con `null` | Transparente y reversible | Métrica de coste incompleta | Elegida para esta etapa |

## Consecuencias

**Positivas:** permite concentrar el trabajo en que la PoC funcione sin simular una
métrica económica exacta.

**Negativas / deuda aceptada:** no habrá coste calculado para ningún modelo hasta
retomar RFC-0005 CA-22.

**Condición de revisión:** antes de cerrar la PoC operativa o de habilitar seguimiento
de costes, poblar `PRICES` con `model_id` versionados y añadir una prueba que demuestre
un coste distinto de `null` para al menos un modelo de producción.
