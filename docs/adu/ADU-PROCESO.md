# ADU — Metodología multiagente de Arquitecto, Desarrollador y Auditor

**Estado:** Aprobado · **Versión:** 1.0 · **Dueño:** Arquitecto

---

## 1. Por qué ADU

Un solo modelo que diseña, implementa y valida su propio trabajo tiene un sesgo estructural:
audita contra su propia interpretación del problema, no contra un contrato externo. ADU
rompe ese bucle repartiendo el trabajo en **tres roles con incentivos distintos**, ejecutados
por **tres modelos distintos**, de forma que el error de un rol tenga que sobrevivir a la
revisión de otro modelo que no lo produjo.

La regla que sostiene todo el método:

> **El artefacto que se audita nunca es el código: es el código *contra el RFC*.**
> Si algo no está en el RFC, no es un defecto de implementación: es un defecto de arquitectura.

## 2. Roles

### A — Arquitecto (Claude Opus 5)

**Responsable de:** PRD, RFCs, ADRs, contratos de interfaz, criterios de aceptación,
priorización y resolución de discrepancias entre Desarrollador y Auditor.

**Produce:** documentos en `docs/`. Esquemas, contratos OpenAPI, DDL, diagramas, presupuestos
de latencia y costo, y el *contrato de auditoría* de cada RFC.

**No hace:** no escribe código de producción, no aprueba su propio diseño contra sí mismo,
no fusiona PRs.

**Límite duro:** si el Desarrollador necesita tomar una decisión de diseño para avanzar,
el trabajo se detiene y vuelve al Arquitecto. *Implementar una decisión no documentada es
un fallo de proceso, no una iniciativa.*

### D — Desarrollador (ChatGPT 5.6)

**Responsable de:** implementar exactamente el alcance de un RFC aprobado **mediante TDD
estricto** (RFC-0014), con sus migraciones y documentación operativa mínima.

**Primera tarea de todo handoff, sin excepción:** producir la **suite de tests en rojo**, en su
propio commit, antes de escribir una sola línea de implementación. Ese commit rojo registrado en
CI es la evidencia de que hubo TDD; sin él, el Auditor emite un hallazgo Mayor.

**Produce:** ramas `feat/rfc-000N-<slug>`, PRs con la plantilla de PR, cobertura de pruebas
según el DoD, y un **Informe de Implementación** que enumera desviaciones respecto al RFC.

**No hace:** no amplía el alcance ("ya que estoy, agrego…"), no cambia contratos públicos,
no modifica los criterios de aceptación, no responde a los hallazgos del Auditor con
justificaciones: los corrige o los escala al Arquitecto.

**Límite duro:** una desviación respecto al RFC es válida solo si está declarada en el
Informe de Implementación. Una desviación no declarada es un hallazgo **Bloqueante** automático.

### U — Auditor (Claude Sonnet 5)

**Responsable de:** verificar el PR contra el contrato de auditoría del RFC y emitir un
veredicto **PASS / PASS-CON-OBSERVACIONES / FAIL**.

**Produce:** un Informe de Auditoría con hallazgos clasificados por severidad, cada uno con
evidencia (archivo:línea, salida de comando, caso de fallo reproducible).

**No hace:** **no modifica código**, no propone refactors de gusto personal, no audita contra
buenas prácticas genéricas que el RFC no exige, no negocia el veredicto.

**Límite duro:** todo hallazgo debe citar la cláusula del RFC o del PRD que se incumple.
Un hallazgo sin cláusula citada es *observación*, nunca *bloqueante*.

### Árbitro

Cuando Desarrollador y Auditor no convergen en dos rondas, decide el **Arquitecto**, y la
decisión se materializa en una modificación del RFC o en un ADR nuevo. Nunca en un acuerdo
verbal dentro del PR.

## 3. Flujo y gates

```
  Necesidad ──G0──> PRD ──G1──> RFC ──G2──> Implementación ──G3──> Auditoría ──G4──> Merge
                                                                                     │
                                                                        G5 ──> QA (VPS) ──G6──> PROD (AWS)
```

| Gate | Transición | Quién decide | Criterio de paso |
| :--- | :--- | :--- | :--- |
| **G0** | Necesidad → PRD | Arquitecto | Problema, usuario y métrica de éxito escritos y medibles |
| **G1** | PRD → RFC | Arquitecto | El RFC cubre un componente completo, con contrato y criterios de aceptación verificables |
| **G2** | RFC → Implementación | Desarrollador acepta | Se cumple el **Definition of Ready** (§4) |
| **G3** | Implementación → Auditoría | Desarrollador entrega | Se cumple el **Definition of Done** (§5) + Informe de Implementación |
| **G4** | Auditoría → Merge | Auditor | Veredicto `PASS` o `PASS-CON-OBSERVACIONES` sin hallazgos Bloqueantes ni Mayores abiertos. Incluye la auditoría de TDD (RFC-0014 §6) |
| **G5** | Merge → QA | CI automático | Pipeline verde + evaluación del agente ≥ umbral (RFC-0009) |
| **G6** | QA → PROD | Arquitecto | Smoke tests en QA + evaluación en QA + revisión de costos y de guardrails |

## 4. Definition of Ready (entrada a G2)

Un RFC es implementable solo si, sin abrir ningún otro documento, responde:

1. **Alcance explícito** — qué entra y, sobre todo, qué **no** entra.
2. **Contrato** — firmas, esquemas de request/response, DDL, nombres de variables de entorno.
3. **Criterios de aceptación** — verificables por una máquina o por un comando concreto.
4. **Estrategia de pruebas** — qué se prueba con unitarias, qué con integración, qué con evals.
5. **Fallos y degradación** — qué hace el sistema cuando la dependencia externa falla.
6. **Dependencias** — RFCs previos que deben estar `Implementado`.
7. **Contrato de auditoría** — la lista cerrada de comprobaciones que hará el Auditor.

Si falta uno solo de los siete puntos, el Desarrollador **rechaza** el RFC y lo devuelve.

## 5. Definition of Done (entrada a G3)

- Todos los criterios de aceptación del RFC pasan y hay evidencia de ello.
- Cobertura de pruebas ≥ 80 % en los módulos tocados; 100 % en la lógica de recuperación,
  de fusión RRF y de autenticación.
- **Historial de commits que demuestra el orden test → implementación por cada criterio, sin
  aplastar** (RFC-0014 §6).
- **Revertir la implementación de cualquier criterio pone su test en rojo.** Es la comprobación
  que el Auditor ejecutará sobre tres criterios elegidos al azar.
- `ruff check`, `ruff format --check`, `mypy --strict` (módulos nuevos) y `pytest` en verde.
- Sin secretos en el repositorio (`gitleaks` en verde).
- Migraciones con `upgrade` **y** `downgrade` probados contra una base efímera.
- Variables de entorno nuevas documentadas en `.env.example` y en el RFC de entornos.
- Informe de Implementación con la lista de desviaciones (o "ninguna").

## 6. Severidad de hallazgos

| Severidad | Definición | Efecto |
| :--- | :--- | :--- |
| **Bloqueante** | Incumple un criterio de aceptación, rompe un contrato público, o introduce riesgo de seguridad/pérdida de datos | `FAIL`. No hay merge. |
| **Mayor** | Cumple el criterio pero por un camino que el RFC prohíbe, o deja un fallo sin manejar declarado en el RFC | `FAIL` salvo excepción firmada por el Arquitecto |
| **Menor** | Divergencia de estilo, nombres o estructura respecto a lo indicado | `PASS-CON-OBSERVACIONES`; se corrige en el mismo PR si es barato |
| **Observación** | Mejora sugerida no exigida por el RFC | No bloquea. Se convierte en issue, nunca en cambio silencioso |

## 7. Contrato de auditoría por RFC

Los prompts literales de los tres roles están en **`docs/adu/prompts/`** y son normativos: se
pegan tal cual. Si el prompt del Auditor cambia entre dos revisiones, sus veredictos dejan de ser
comparables y el gate G4 deja de significar algo.

Cada RFC termina con una sección `## Contrato de auditoría (gate ADU)` que contiene una
**lista cerrada y numerada** de comprobaciones. El Auditor no inventa comprobaciones nuevas:
si detecta un riesgo fuera de la lista, lo emite como *Observación* y propone al Arquitecto
ampliar el contrato del RFC para el siguiente ciclo.

Formato de cada comprobación:

```
| # | Comprobación | Cómo se verifica | Severidad si falla |
```

Esto hace la auditoría **reproducible**: dos ejecuciones del Auditor sobre el mismo PR deben
producir el mismo veredicto.

## 8. Handoffs (formato de mensaje entre roles)

### Arquitecto → Desarrollador

```
RFC: RFC-000N — <título>
Rama: feat/rfc-000N-<slug>
Alcance cerrado: <resumen de 3 líneas>
Fuera de alcance: <lista>
Criterios de aceptación: ver §Criterios del RFC
Bloqueos conocidos: <RFCs pendientes o accesos requeridos>
Primera entrega esperada: suite de tests EN ROJO, en su propio commit.
```

> Los prompts completos de los tres roles están en `docs/adu/prompts/`. Lo anterior es el
> mensaje de traspaso que los acompaña.

### Desarrollador → Auditor (Informe de Implementación)

```
RFC: RFC-000N
PR: #<n>  ·  Commits: <rango>
Archivos tocados: <lista>
Criterios de aceptación cubiertos: <N/N> con evidencia por criterio
Mapa criterio -> test (commit del test en rojo / commit de implementación en verde)
Desviaciones respecto al RFC: <lista con justificación, o "ninguna">
Deuda declarada: <lista, o "ninguna">
Cómo reproducir las pruebas: <comandos>
```

### Auditor → Arquitecto (Informe de Auditoría)

```
RFC: RFC-000N  ·  PR: #<n>
Veredicto: PASS | PASS-CON-OBSERVACIONES | FAIL
Comprobaciones del contrato: <N aprobadas / M totales>
Hallazgos:
  [Bloqueante] <descripción> · Cláusula: <RFC §x.y> · Evidencia: <archivo:línea | salida>
  [Mayor] ...
  [Menor] ...
  [Observación] ...
Riesgos fuera del contrato de auditoría (para ampliar el RFC): <lista>
```

## 9. Trazabilidad

- Rama por RFC: `feat/rfc-000N-<slug>`.
- Commits: `<tipo>(<ámbito>): <descripción> [RFC-000N]`.
- PR: título `[RFC-000N] <título>`; cuerpo con el Informe de Implementación.
- El Informe de Auditoría se publica como comentario del PR y se archiva en
  `docs/auditorias/RFC-000N-pr<N>.md` cuando el veredicto es `FAIL` (para aprender del patrón).

## 10. Antipatrones que este proceso existe para impedir

| Antipatrón | Cómo lo corta ADU |
| :--- | :--- | 
| "El código funciona, ya veremos la documentación" | Sin RFC aprobado no hay rama (G2) |
| "Aprovecho y refactorizo esto de paso" | Alcance cerrado + desviaciones declaradas |
| "El agente responde bien, lo probé a mano" | Evaluación automatizada como gate de merge (RFC-0009) |
| "Lo arreglo directo en producción" | G6 exige paso previo por QA con la misma imagen |
| El auditor reescribe el código que audita | El Auditor no tiene permiso de escritura |
| Auditorías que cambian de criterio cada vez | Contrato de auditoría cerrado y numerado por RFC |
