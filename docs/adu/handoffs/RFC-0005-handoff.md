# Handoff Arquitecto → Desarrollador — RFC-0005

Formato de ADU-PROCESO §8. Se archiva porque un handoff que solo vive en un chat no existe para
quien audita después.

```
RFC: RFC-0005 — API REST: contrato, autenticación por API Key y límites de uso
Rama: feat/rfc-0005-api-rest
Punto del plan: 9 (Fase 2)
```

## Gate G2 — Definition of Ready

**Rechazado en la primera pasada y corregido en este PR.** El documento se escribió cuando la PoC
todavía iba a AWS y nadie revisó las justificaciones que quedaron atrás.

| # | Punto del DoR | Estado |
| :--- | :--- | :--- |
| 1 | Alcance explícito, con lo que no entra | §2, §13.6 |
| 2 | Contrato | §3–§9, §13 — **§3.1 y §3.2 nuevas**: `/healthz`, `/readyz` y los endpoints admin no tenían contrato |
| 3 | Criterios de aceptación verificables | §11, CA-1..CA-12, CA-14..CA-25 (**CA-20..CA-25 nuevas**; CA-13 sigue retirada a RFC-0021) |
| 4 | Estrategia de pruebas | **§14, nueva.** No existía |
| 5 | Fallos y degradación | §10, corregida |
| 6 | Dependencias | Cabecera, ampliada: faltaban RFC-0013, RFC-0019, RFC-0020, RFC-0021 y la fila de ADRs |
| 7 | Contrato de auditoría | A-1..A-21 (**A-17..A-21 nuevas**, A-10 reescrita) |

Los cuatro defectos de fondo que motivaron el rechazo están en el blockquote de cabecera del RFC.
El más caro habría sido §6.1: un Desarrollador que lo siguiera habría añadido `boto3` y un cliente
de AWS Secrets Manager para leer una credencial que vive en un archivo local del VPS — y **A-10
auditaba ese mismo mecanismo retirado**, así que el gate lo habría aprobado.

## Alcance cerrado

Los endpoints de §3 con sus contratos: `/healthz` y `/readyz` (§3.1), `/v1/chat` (§4),
`/v1/chat/stream` (§5), `/v1/responses` (§13), `/v1/conversations/{id}`, `/v1/meta`, y los
administrativos de §3.2. Autenticación por API Key y roles (§6), límite de tasa (§7), formato de
error (§8), CORS y versionado (§9). Más `app/core/pricing.py`, que **este punto crea** (§4).

## Fuera de alcance

La capa de agente (RFC-0004, ya implementada — `build_agent()` y `stream_turn()` se **consumen**),
la búsqueda (RFC-0003), la evaluación y los guardrails (RFC-0009, punto 10), la ejecución de la
ingesta (RFC-0019 — esta API **encola**, el cron ejecuta), el despliegue (RFC-0020, punto 11) y
PROD entero (RFC-0016).

## Invariantes que el Auditor va a mirar primero

1. **Ninguna prueba automática llama a una API de pago** (A-17, Bloqueante, ADR-0012). El modelo se
   dobla siempre con el `ScriptedModel` de RFC-0004 §12 — que ya existe en
   `tests/integration/agent_fixtures.py`. Se dobla **el modelo, no el agente**: doblar el agente
   probaría el doble, no la API (P-2).
2. **`app/` no lee ningún secreto de AWS** (A-18, Bloqueante). `rg -n "secretsmanager|boto3|
   API_KEYS_SECRET_ID" app/` sin resultados. Ojo: `boto3` está instalado como dependencia base de
   `strands-agents` (ADR-0013) — lo que se prohíbe es **usarlo**, no que exista en el entorno.
3. **Todas las rutas `/v1/*` exigen autenticación; `/healthz` y `/readyz` no** (A-4, Bloqueante).
4. **Los errores no filtran internos** (A-5, Bloqueante, invariante I-6). Ningún cuerpo con trazas,
   SQL ni nombres de recursos. `checks.database` de §3.1 **no** cuenta: es un nombre fijo.
5. **El aislamiento de conversaciones por `key_id`** (A-9, Bloqueante): otra clave ⇒ `404`, no `403`.

## Bloqueos conocidos

- **`app/core/pricing.py` y `app/core/security.py` no existen.** Los crea este punto. RFC-0014 §8
  exige **100 % de ramas** en `app/core/security.py` — es el umbral más alto del repositorio, y no
  es negociable: ahí vive la verificación de claves.
- **`/readyz` ya existe** en `app/main.py` con una versión mínima; este punto lo amplía al contrato
  de §3.1. No se reescribe desde cero.
- **`rate_buckets` ya existe** como tabla (RFC-0006) y como módulo (`app/core/rate_buckets.py`).
  Se consume, no se reimplementa.
- **El `commit_sha` de `/readyz` se lee del artefacto de la *release*, no de `git`**: el VPS no
  tiene el repositorio (RFC-0020 §6). Cómo llega ese valor al artefacto es de RFC-0020/RFC-0008;
  aquí se lee de la configuración y se sirve. Si no está disponible, el campo va `null` — no se
  inventa ni se ejecuta `git` en tiempo de ejecución.

## Nota sobre TDD

Aplica la **forma por criterio** (RFC-0014 §6.1.1): la mayoría de los criterios de §11 son
separables (autenticación, roles, límite de tasa, formato de error, `/docs`, SSE, precios). Van
juntos solo los que comparten unidad de implementación —CA-1/CA-2/CA-4, que comparten el verificador
de claves—; revertir ese verificador los enrojece a los tres a la vez.

Las tres trampas que costaron rondas en PR #73 y #78, para no repetirlas:

- **El rojo tiene que ser conductual.** Un `ModuleNotFoundError` no demuestra nada (RFC-0014 §3):
  se crea antes el módulo con la firma y un cuerpo que lance `NotImplementedError`.
- **El verde no toca `tests/`** (P-9, Bloqueante). Si al implementar el test falla por su propia
  aserción mal escrita, se revierte producción, se corrige el test en su propio commit —comprobando
  que sigue rojo por la razón correcta— y recién después se aplica la implementación.
- **Un criterio nuevo necesita su propio rojo.** No vale apoyarse en el par rojo/verde de otro
  criterio "porque el mecanismo ya estaba probado": si es la primera vez que ese comportamiento se
  afirma, va con su par, o con la reparación por regresión deliberada de §6.2.2.

## Primera entrega esperada

Suite de tests **en rojo**, en su propio commit, con PR en borrador abierto **antes** de ese commit
para que el CI lo registre por SHA (RFC-0014 §6.2).
