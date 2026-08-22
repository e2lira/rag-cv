# Prompts de ejecución multimodelo (ADU)

Los tres prompts de esta carpeta son **normativos**: se pegan tal cual al inicio de cada sesión,
sustituyendo solo las variables entre `<>`. No se improvisan ni se resumen.

La razón es la reproducibilidad. Si el prompt del Auditor cambia entre dos revisiones, sus
veredictos dejan de ser comparables y el gate G4 deja de significar algo. Lo mismo vale para el
Desarrollador: el orden tests-primero solo es exigible si está escrito.

| Rol | Modelo | Prompt | Entrega |
| :--- | :--- | :--- | :--- |
| **Arquitecto** | Claude Opus 5 | [PROMPT-ARQUITECTO.md](./PROMPT-ARQUITECTO.md) | PRD, RFCs, ADRs. **Ningún código de producción** |
| **Desarrollador** | Claude Sonnet 5 | [PROMPT-DESARROLLADOR-TDD.md](./PROMPT-DESARROLLADOR-TDD.md) | Tests en rojo → implementación → PR |
| **Auditor** | ChatGPT 5.6 Terra | [PROMPT-AUDITOR.md](./PROMPT-AUDITOR.md) | Veredicto PASS / PASS-CON-OBSERVACIONES / FAIL |

## Ciclo completo de un RFC

```
Arquitecto ──RFC aprobado──> Desarrollador ──commit de tests EN ROJO──┐
                                                                      │
                                   ┌──────────────────────────────────┘
                                   v
                        implementación (verde) ──PR + Informe──> Auditor
                                                                    │
                              ┌─────────────────────────────────────┤
                              v                                     v
                        FAIL: vuelve al                    PASS: merge (G4)
                        Desarrollador                      y despliegue a QA (G5)
```

Si Desarrollador y Auditor no convergen en dos rondas, decide el **Arquitecto**, y la decisión se
materializa modificando el RFC o abriendo un ADR. Nunca en un acuerdo dentro del PR
(ADU-PROCESO §2).

## Nota sobre el LLM del producto

Estos prompts son del **proceso de desarrollo**. No tienen relación con el LLM que usa el agente
en ejecución: ese se designa por parametrización (`PROVEEDOR`, RFC-0013) y su prompt de sistema
vive en `app/agent/prompts.py`, versionado con `SYSTEM_PROMPT_VERSION`.
