## Issue aprobado (obligatorio)

<!-- El issue enlazado debe tener status:approved. Usá: Closes #<issue>, Fixes #<issue> o Resolves #<issue>. -->

Closes #<issue>

## Título y RFC (obligatorio)

<!-- El título del PR debe ser: [RFC-000N] <título>. -->

RFC: RFC-000N

## Alcance y Definition of Ready

<!-- Alcance cerrado, fuera de alcance y evidencia de que el RFC cumple DoR. -->

- Alcance:
- Fuera de alcance:
- DoR del RFC verificado: [ ]

## Tipo de PR (obligatorio)

Marcá **exactamente uno** y agregá al PR esa misma y única etiqueta `type:*`:

- [ ] Bug fix — `type:bug`
- [ ] Nueva funcionalidad — `type:feature`
- [ ] Solo documentación — `type:docs`
- [ ] Refactorización — `type:refactor`
- [ ] Mantenimiento/herramientas — `type:chore`
- [ ] Cambio incompatible — `type:breaking-change`

## Resumen

<!-- Problema y cambio en 1–3 líneas. -->

## Revisar primero

<!-- Indicá el archivo, contrato o riesgo que el revisor debe revisar primero. -->

## Cambios

| Archivo o área | Cambio |
|---|---|
| `ruta/archivo` | Describí el cambio. |

## Área del proyecto afectada

Marcá todas las áreas que toca esta rama:

- [ ] Domain
- [ ] Application / casos de uso
- [ ] API / adapters
- [ ] Base de datos / migraciones
- [ ] Ingestión / índice / HNSW
- [ ] Infraestructura AWS
- [ ] QA / CI/CD
- [ ] Documentación
- [ ] Documentación — diagramas (C4, AWS, hoja de ruta)
- [ ] Seguridad

## Impacto y riesgo

<!-- Impacto en usuarios, datos, costos, rendimiento u operación; riesgos y mitigaciones. -->

## Datos, migraciones e índice

- [ ] No afecta base de datos ni reindexado.
- [ ] Incluye migración; describí compatibilidad y orden de despliegue:
- [ ] Afecta ingestión/HNSW; describí idempotencia, ventana de mantenimiento y reversión:

## Plan de pruebas y evaluación

<!-- Comandos, resultados y métricas RAG si aplica. -->

- [ ] Pruebas automatizadas relevantes en verde.
- [ ] `shellcheck` ejecutado para scripts modificados, o no aplica.
- [ ] Validación manual de la funcionalidad afectada.

## Informe de Implementación ADU

<!-- Para cada criterio, enlazá el test y los commits que prueban Rojo → Verde. -->

| Criterio del RFC | Test | Commit test (rojo) | Commit implementación (verde) |
|---|---|---|---|
| CA-N | `ruta/test` | `abc1234` | `def5678` |

- Desviaciones respecto al RFC: ninguna / describir y justificar.
- Waivers o excepciones aprobadas: ninguna / enlazar decisión del Arquitecto.
- Cómo reproducir la evidencia:

## Conclusión del Auditor ADU

<!-- Pegá o enlazá el Informe de Auditoría: PASS, PASS-CON-OBSERVACIONES o FAIL, con hallazgos abiertos. -->

- Veredicto:
- Hallazgos abiertos:

## Ambiente verificado

- [ ] DEV (Windows)
- [ ] QA (Ubuntu VPS)
- [ ] PROD/AWS (solo configuración o despliegue autorizado)

## Rollback

<!-- Cómo se revierte de forma segura; indicá explícitamente si no aplica. -->

## Fuera de alcance

<!-- Qué NO resuelve este PR. -->

## Checklist del contribuidor

- [ ] El issue enlazado está aprobado y usa `Closes`, `Fixes` o `Resolves #<issue>`.
- [ ] Agregué exactamente una etiqueta `type:*` que coincide con el tipo seleccionado.
- [ ] Ejecuté `shellcheck` para scripts modificados, o documenté por qué no aplica.
- [ ] Probé las skills afectadas en al menos un agente, o documenté por qué no aplica.
- [ ] Actualicé la documentación si cambió el comportamiento.
- [ ] Los commits siguen Conventional Commits.
- [ ] No agregué trailers `Co-Authored-By`.
