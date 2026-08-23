# ADR-0011 — Excepciones firmadas a la disciplina TDD

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aceptada |
| **Fecha** | 2026-08-23 |
| **Decide** | Arquitecto |
| **Afecta a** | RFC-0014, PR #16, PR #21 |

---

## Contexto

ADU-PROCESO §Árbitro dice, textualmente:

> Cuando Desarrollador y Auditor no convergen en dos rondas, decide el **Arquitecto**, y la
> decisión se materializa en una modificación del RFC o en un ADR nuevo. **Nunca en un acuerdo
> verbal dentro del PR.**

Firmé dos excepciones a la disciplina TDD —una en PR #16, otra en PR #21— y **las dejé
únicamente como comentarios del PR**. Es exactamente lo que esa cláusula prohíbe, y la escribí yo.

La consecuencia llegó puntual: la tercera ronda de auditoría de PR #21 volvió a levantar como
hallazgo Mayor la brecha TDD que ya tenía excepción firmada. El Auditor no hizo nada mal — audita
contra los documentos, y en los documentos no había nada. Una decisión que solo existe en un hilo
de conversación no existe para quien audita después.

Este ADR es el registro que debí haber creado entonces.

## Decisión

Quedan firmadas las dos excepciones siguientes. Ambas son **acotadas, cerradas y no
extensibles**: nombran su PR y su conjunto exacto de criterios, y ninguna crea precedente para un
PR posterior.

### E-1 · PR #16 (RFC-0011) — sin evidencia CI roja→verde en los commits de test originales

| Campo | Valor |
| :--- | :--- |
| **Cláusula excepcionada** | RFC-0014 §6.2 |
| **Alcance** | Commits `a5905a3..7ff10a3` de PR #16 |
| **Motivo** | El *workflow* de CI se introduce en ese mismo PR (commit `906fd19`): no existía *runner* donde esos commits pudieran haber corrido en rojo |
| **Evidencia sustituta verificada** | Orden de commits íntegro sin *squash*; TDD-3 en verde sobre CA-0', CA-4 y CA-5; CI verde sobre el `HEAD` final con la suite real |
| **Causa corregida en** | RFC-0014 §6.2.1 (excepción de arranque, una sola vez por repositorio) |

### E-2 · PR #21 (RFC-0006) — commits de test posteriores a la migración que ya los satisfacía

| Campo | Valor |
| :--- | :--- |
| **Cláusula excepcionada** | RFC-0014 §6.1 y §6.2 |
| **Alcance** | CA-2 a CA-5 y CA-9 a CA-12 de PR #21 |
| **Motivo** | El contrato prescribía **dos formas incompatibles** del ciclo TDD sin decir cuál aplicaba (ADU-PROCESO §3 y el prompt del Desarrollador pedían la suite completa en un commit; RFC-0014 §6.1 ilustraba pares por criterio). El Desarrollador aplicó una de las dos, y para un RFC cuya implementación es una sola migración eso produce necesariamente commits de test posteriores |
| **Evidencia sustituta verificada** | TDD-3 en verde (confirmado por el propio Auditor en las tres rondas); historial sin *squash*; verificación manual por reversión declarada en el Informe de Implementación |
| **Causa corregida en** | RFC-0014 §6.1.1 (cuál de las dos formas es obligatoria, con criterio de decisión mecánico) |
| **No cubre** | CA-13 a CA-19, que sí siguieron la forma de suite completa (`dfdeac7` rojo → `e5ab086` verde) y no necesitan excepción |

## Consecuencias

- El Auditor puede cerrar TDD-1/TDD-2 sobre los criterios listados citando este ADR, sin
  depender de haber leído un comentario de PR.
- Ninguna de las dos excepciones se extiende a un PR futuro. Sus causas están corregidas en
  RFC-0014 §6.1.1 y §6.2.1, así que un PR posterior que reincida **no** tiene excepción: tiene un
  hallazgo Mayor.
- Toda excepción futura del Arquitecto se registra aquí o en un ADR propio **antes** de darse por
  aplicada. Una excepción que solo vive en un comentario no es una excepción: es un acuerdo
  verbal, y el proceso los prohíbe precisamente porque desaparecen.

## Alternativas descartadas

**Reescribir el historial para fabricar la evidencia.** Habría producido comprobantes de un
proceso que no ocurrió así, y RFC-0014 §6.1 prohíbe el *squash* justo porque el historial es la
evidencia. Falsificar la evidencia para satisfacer al auditor de la evidencia es peor que la
brecha que corrige.

**Relajar RFC-0014 para que los casos dejen de ser hallazgo.** Convierte la excepción en el
mecanismo por defecto — el antipatrón que ADU-PROCESO §10 existe para cortar. Las dos causas se
corrigieron con reglas *más* precisas, no más laxas.
