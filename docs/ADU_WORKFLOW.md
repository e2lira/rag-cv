# ADU — índice operativo

Este archivo es el punto de entrada para ejecutar ADU en `rag-cv`; no redefine el proceso. La autoridad normativa está en [`docs/adu/ADU-PROCESO.md`](adu/ADU-PROCESO.md) y en los prompts canónicos de [`docs/adu/prompts/`](adu/prompts/). Ante cualquier diferencia, prevalecen esos documentos.

## Inicio rápido

1. Leé el [proceso ADU](adu/ADU-PROCESO.md) y verificá que el trabajo tiene un RFC aprobado y listo para el gate correspondiente.
2. Para diseño, copiá y ejecutá **sin modificar** [`PROMPT-ARQUITECTO.md`](adu/prompts/PROMPT-ARQUITECTO.md).
3. Para implementar, copiá y ejecutá **sin modificar** [`PROMPT-DESARROLLADOR-TDD.md`](adu/prompts/PROMPT-DESARROLLADOR-TDD.md).
4. Para auditar el PR, copiá y ejecutá **sin modificar** [`PROMPT-AUDITOR.md`](adu/prompts/PROMPT-AUDITOR.md).
5. Seguí los gates, handoffs y condiciones de promoción definidos en el proceso canónico.

Los prompts son normativos y pertenecen a sus archivos canónicos: no se resumen, adaptan ni sustituyen desde este índice. En particular, la definición de roles, el alcance de RFC/Definition of Ready/Definition of Done, la evidencia de TDD, el contrato de auditoría y los formatos de informe se ejecutan desde las fuentes enlazadas.

## Mapa de operación

| Momento | Fuente canónica que se ejecuta | Resultado esperado |
|---|---|---|
| Preparar una necesidad | [ADU-PROCESO](adu/ADU-PROCESO.md) | PRD/RFC y gate de entrada según el proceso. |
| Diseñar o resolver una discrepancia | [Prompt del Arquitecto](adu/prompts/PROMPT-ARQUITECTO.md) | Artefacto de arquitectura aprobado. |
| Implementar un RFC | [Prompt del Desarrollador — TDD](adu/prompts/PROMPT-DESARROLLADOR-TDD.md) | PR e Informe de Implementación conforme al RFC. |
| Verificar un PR | [Prompt del Auditor](adu/prompts/PROMPT-AUDITOR.md) | Informe de Auditoría y veredicto. |
| Promover a QA/PROD | [Gates del proceso ADU](adu/ADU-PROCESO.md) | Evidencia de CI, QA y aprobación requerida. |

## Primera porción de RAG-CV

La primera porción planificada es la ingesta de `cv.md` y su indexación idempotente. Bajo el alcance vigente la fuente es el **fichero local** `corpus/cv.md`, no S3: la ingesta por eventos de S3 queda diferida junto con el resto de AWS y su disparador lo asume un sondeo programado ([ADR-0006](adr/ADR-0006-entorno-de-entrega-de-la-poc.md), [ADR-0009](adr/ADR-0009-deteccion-de-cambios-del-corpus-por-sondeo.md), [RFC-0016 §3.3](rfc/RFC-0016-alcance-poc-y-entrega-en-qa.md), [RFC-0019](rfc/RFC-0019-deteccion-de-cambios-del-corpus-en-el-vps.md)). Se ejecuta únicamente cuando exista el RFC aprobado y se usan los prompts canónicos anteriores de forma literal.

## Referencias

- [`docs/adu/ADU-PROCESO.md`](adu/ADU-PROCESO.md) — metodología, gates, contratos y handoffs.
- [`docs/adu/prompts/PROMPT-ARQUITECTO.md`](adu/prompts/PROMPT-ARQUITECTO.md) — prompt normativo del Arquitecto.
- [`docs/adu/prompts/PROMPT-DESARROLLADOR-TDD.md`](adu/prompts/PROMPT-DESARROLLADOR-TDD.md) — prompt normativo del Desarrollador.
- [`docs/adu/prompts/PROMPT-AUDITOR.md`](adu/prompts/PROMPT-AUDITOR.md) — prompt normativo del Auditor.