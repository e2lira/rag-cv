# Handoff Arquitecto → Desarrollador — RFC-0004

Formato de ADU-PROCESO §8. Se archiva porque un handoff que solo vive en un chat no existe para
quien audita después — la misma razón por la que ADR-0011 obliga a registrar las excepciones.

```
RFC: RFC-0004 — Capa de agente con Strands Agents
Rama: feat/rfc-0004-capa-agente
```

## Gate G2 — Definition of Ready

**Verificado y aprobado**, con siete correcciones aplicadas antes de este handoff (PR de enmienda).
El RFC tenía las siete secciones del DoR, pero cuatro describían un sistema retirado: título y §3
fijaban Bedrock como proveedor activo (ADR-0008 designó Anthropic), §6.1 pedía credenciales de AWS
que RFC-0018 §4 retiró, §10 nombraba excepciones de `botocore` que con `PROVEEDOR=anthropic` no se
lanzan nunca, y §12 exigía integración contra Bedrock real, que **contradice ADR-0012**.

| # | Punto del DoR | Estado |
| :--- | :--- | :--- |
| 1 | Alcance explícito, con lo que no entra | §2 |
| 2 | Contrato (firmas, prompt, herramientas) | §3–§6 |
| 3 | Criterios de aceptación verificables | §11, CA-1..CA-10 + tres heredados |
| 4 | Estrategia de pruebas | §12 |
| 5 | Fallos y degradación | §10 |
| 6 | Dependencias | RFC-0003 ✅, RFC-0013 ✅ (ambos implementados y en `main`) |
| 7 | Contrato de auditoría | A-1..A-12 |

## Alcance cerrado

`app/agent/`: el prompt de sistema versionado (§4), las **dos** herramientas `search_cv` y
`list_cv_sections` (§5), `build_agent()` que recibe el modelo ya construido por `build_model()`
(§6), la memoria por `conversation_id` (§7), los límites duros de ejecución (§8) y un único flujo
de eventos para *streaming* (§9).

## Fuera de alcance

La búsqueda (RFC-0003, ya implementada — se **consume**, no se toca), la API HTTP y sus endpoints
(RFC-0005, punto 9), la evaluación y los guardrails de contenido (RFC-0009, punto 10), y la
construcción del modelo (RFC-0013, ya implementada — `build_model()` se **llama**, no se
reimplementa).

## Criterios de aceptación

§11 del RFC: CA-1 a CA-10 propios, **más tres heredados** que se difirieron aquí en PR #71/#72
porque verifican `app/agent/`, que no existía cuando se auditaron sus RFC de origen:

| Origen | Criterio |
| :--- | :--- |
| RFC-0013 CA-6 / A-5 | `app/agent/` no menciona ningún proveedor concreto |
| RFC-0013 CA-10 | El mismo prompt de sistema se usa con los tres proveedores |
| RFC-0018 CA-7 | El prompt de sistema es idéntico al de cualquier otro proveedor |

El Informe de Implementación debe cubrirlos **con su nombre de origen**, no renombrados: el
Auditor de aquellos RFC los busca por ese identificador.

## Invariantes que el Auditor va a mirar primero

1. **I-9 — `app/agent/` no nombra ningún proveedor.** `grep -rn "Bedrock\|Anthropic\|OpenAI"
   app/agent/` sin resultados. Es A-6b, Bloqueante, y además cierra dos criterios heredados.
2. **El objeto `Agent` no guarda estado conversacional entre peticiones** (A-1, Bloqueante). Se
   construye una vez por proceso en el `lifespan`; el historial se pasa por invocación. Una fuga de
   contexto entre usuarios es el error más caro de esta arquitectura.
3. **Ninguna prueba automática llama a una API de pago** (A-10, ADR-0012). El modelo se dobla
   siempre, con guion fijo.
4. **Solo dos herramientas registradas** (A-6, Bloqueante). Nada de internet, ejecución de código
   ni lectura de archivos.

## Bloqueos conocidos

- **`tests/adversarial/` no existe y no hay marcador `adversarial`.** `pyproject.toml` solo declara
  `unit` e `integration`. Un marcador no declarado **no falla: se ignora**, y la prueba corre donde
  no debía. Si hacen falta las adversariales en su propio directorio, declarar el marcador en
  `pyproject.toml` **en el mismo PR**, en su propio commit `chore`.
- **`app/core/pricing.py` no existe todavía.** RFC-0005 §4 lo nombra para `usage.cost_usd`. No
  bloquea este punto: el coste se publica en el punto 9, no aquí.

## Nota sobre TDD

Se aplica la **forma por criterio** (RFC-0014 §6.1.1): revertir el prompt no rompe los límites de
ejecución, ni al revés. La excepción es CA-6/CA-7 (adversariales), que comparten el prompt como
unidad de implementación y van juntas.

Recordatorio de las dos trampas que ya costaron rondas de auditoría en este repo, ambas guardadas
en el historial de PR #73:

- **Verificar localmente no es evidencia.** El rojo tiene que quedar registrado en CI **por su
  propio SHA**, en *todos* los jobs.
- **El verde tiene que ocurrir en el commit que cambia el código de producción**, no en una
  corrección posterior que solo toca tests — aunque esa corrección sea legítima.

## Primera entrega esperada

Suite de tests **en rojo**, en su propio commit, con PR en borrador abierto **antes** de ese
commit para que el CI lo registre por SHA (RFC-0014 §6.2).
