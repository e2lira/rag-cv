# RFC-XXXX — <Título>

| Campo | Valor |
| :--- | :--- |
| **Estado** | Borrador / En revisión / Aprobado / Implementado / Obsoleto |
| **Autor** | Arquitecto (Claude Opus 5) |
| **Implementa** | Desarrollador (Claude Sonnet 5) |
| **Audita** | Auditor (ChatGPT 5.6 Terra) |
| **Depende de** | RFC-XXXX, RFC-YYYY |
| **Superseded by** | — |
| **Fecha** | AAAA-MM-DD |

## 1. Contexto y problema

Qué necesidad del PRD cubre este RFC y qué duele hoy. Máximo 10 líneas.

## 2. Alcance

**Entra:**
- …

**No entra (explícito):**
- …

## 3. Diseño

Decisiones, diagramas, flujo de datos. Las alternativas descartadas van a un ADR, no aquí.

## 4. Contrato

Firmas de funciones, esquemas de request/response, DDL, nombres exactos de variables de
entorno, formatos de error. Todo lo que otro componente pueda asumir.

## 5. Criterios de aceptación

Numerados y verificables. Cada uno debe poder responderse con un comando o una prueba.

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | … | `pytest tests/...::test_x` |

## 6. Estrategia de pruebas

Unitarias / integración / evaluación del agente. Qué se mockea y qué no.

## 7. Fallos y degradación

| Fallo | Detección | Comportamiento esperado |
| :--- | :--- | :--- |

## 8. Impacto operativo

Latencia, costo, migraciones, variables nuevas, cambios de infraestructura.

## 9. Riesgos y mitigaciones

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | … | … | Bloqueante |
