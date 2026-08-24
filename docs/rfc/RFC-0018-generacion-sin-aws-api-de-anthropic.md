# RFC-0018 — Generación sin AWS: API de Anthropic

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0013, RFC-0009, RFC-0016 |
| **Supersede** | RFC-0013 §4 (valor por defecto de `PROVEEDOR`); RFC-0007 §5.2 (credenciales de AWS en QA), que queda **derogado** para la PoC |
| **ADRs** | ADR-0008 |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

ADR-0008 designa la API de Anthropic como proveedor de generación de la PoC. Este RFC es el
contrato de ese cambio, y es deliberadamente corto: **RFC-0013 ya hizo el trabajo difícil.**

Lo que no cambia:

- **La fábrica `build_model` no se toca.** La rama `anthropic` ya existe (RFC-0013 §3), con su
  `import` dentro de la rama y su extra de instalación propio.
- **`Settings` no se toca.** Ya valida por rama: `PROVEEDOR=anthropic` exige `ANTHROPIC_API_KEY`
  y `ANTHROPIC_MODEL_ID` (RFC-0013 §4).
- **El prompt de sistema no se toca.** Es único y agnóstico del proveedor (RFC-0004 §4), que es lo
  que hace que una comparativa mida el modelo y no dos prompts distintos.
- **El *fallback* sigue apagado por defecto** (ADR-0005). Este RFC no lo enciende.

Cambia el valor de tres variables de entorno. Que el cambio sea de este tamaño **es la
verificación de RNF-13**, no una casualidad.

## 2. Alcance

**Entra:** la configuración vigente del proveedor, la gestión del secreto en el VPS, la retirada
de la credencial de AWS de QA, el efecto sobre el juez de evaluación y sobre el presupuesto de
coste.

**No entra:** la fábrica ni el contrato de la capa de proveedores (RFC-0013, vigente), el prompt
de sistema (RFC-0004), los embeddings (RFC-0017).

## 3. Configuración

| Variable | Valor en la PoC | Nota |
| :--- | :--- | :--- |
| `PROVEEDOR` | `anthropic` | Sustituye al `bedrock` por defecto de RFC-0013 §4 |
| `ANTHROPIC_MODEL_ID` | `claude-haiku-4-5-20251001` | **El mismo modelo** que designaba ADR-0005; cambia el camino, no el modelo. **Versión con fecha, no el alias `claude-haiku-4-5`** (ADR-0012): un alias avanza solo, y entonces la línea base de `evals/baselines/` deja de corresponder al modelo que responde — sin que nada falle |
| `ANTHROPIC_API_KEY` | secreto | `$RAG_CV_HOME/.env`, permisos `600` (RFC-0016 §8.1) |
| `AWS_REGION`, `BEDROCK_MODEL_ID` | **ausentes** | No vacías: ausentes (RFC-0016 §7) |
| `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` | sin cambios | RFC-0013 |

Conservar `claude-haiku-4-5` es la decisión de fondo, no un detalle. La PoC cambia el embedder
(RFC-0017), que es la variable capaz de mover la calidad de la recuperación. Si además cambiara el
modelo de generación, **una caída en las métricas de RFC-0009 sería inatribuible**: no se podría
distinguir "recuperó mal" de "redactó mal". Con el generador fijo, la primera evaluación mide una
sola cosa.

## 4. Retirada de la credencial de AWS en QA

RFC-0007 §5.2 especificaba para QA un usuario IAM `rag-cv-qa-invoker`, con claves en el `.env`
—bajo `/opt/rag-cv`, ruta que RFC-0016 §8.1 reubica— y rotación cada 90 días. Con RFC-0017 y este
RFC, **ningún componente de la PoC llama a AWS**, así que esa sección queda derogada para el
alcance vigente y el usuario IAM se elimina.

Efectos concretos:

- Desaparece la rotación de claves de AWS del runbook (RFC-0010).
- Desaparece el paso manual de **habilitar el acceso al modelo en la consola de Bedrock** por
  cuenta y región — el que producía un `AccessDeniedException` que parecía un problema de política
  IAM y no lo era.
- Los secretos de larga vida de la PoC quedan en **dos**: `ANTHROPIC_API_KEY` y, desde ADR-0007,
  `OPENAI_API_KEY` para los embeddings. Siguen siendo menos que el diseño original, que además
  exigía credenciales de AWS.

Se declara sin adornos: RNF-8 se sigue cumpliendo —el secreto no vive en el repositorio— pero se
pierde el "cero claves" que el rol de instancia daba en el PROD diferido. Es un secreto menos que
antes y uno más que en el diseño de PROD.

Y hay un segundo matiz que no conviene callar: la operación corre con una cuenta de inicio de
sesión, no con un usuario de servicio sin shell (RFC-0016 §8.1), así que **quien entre por SSH
como `qrimapp-reto` lee ese secreto**. Los permisos `600` protegen frente a otras cuentas del
host, no frente a la propia. Se acota con acceso por clave y sin contraseña (RFC-0007 §5.1), y se
declara aquí para que la elección de operar sin `root` no se confunda con una frontera de
seguridad: no lo es (RFC-0016 §8.1).

## 5. Efecto sobre la evaluación

RFC-0009 §4.1 exige que el juez sea **el modelo más capaz disponible** y que **no sea el mismo
modelo que genera la respuesta**. Con `PROVEEDOR=anthropic` y el agente sobre Haiku 4.5, un juez
Anthropic superior cumple ambas condiciones al pie de la letra.

Pero hay una objeción que este RFC prefiere dejar escrita antes de que la levante una auditoría:
**juez y agente del mismo proveedor comparten sesgos de entrenamiento**, que es exactamente el
argumento con el que ADU reparte sus tres roles entre modelos de proveedores distintos
(`docs/adu/ADU-PROCESO.md` §2). `EVAL_JUDGE_PROVEEDOR` es independiente de `PROVEEDOR` (RFC-0009
§4.1) precisamente para poder apuntar el juez a otro proveedor.

**La decisión se toma con la calibración, no con la intuición.** RFC-0009 §4.1 fija 15 casos con
veredicto humano: si el juez discrepa por encima del margen tolerado, no sirve como gate hasta
recalibrar. Ese mecanismo ya existe y es el que resuelve esta cuestión con evidencia. Lo que este
RFC exige es que la calibración se ejecute y se publique **antes** de usar el juez como gate de
merge (CA-4).

## 6. Coste

Sin infraestructura que lo acote, el pago por token queda gobernado por dos umbrales que ya
existen y que **no se relajan**:

| Umbral | Valor | Origen |
| :--- | :--- | :--- |
| Costo por conversación de 5 turnos | ≤ USD 0.05 | RNF-5 |
| Costo medio por caso de evaluación | ≤ USD 0.012 | RFC-0009 §4 |

`usage.cost_usd` se sigue registrando por petición (RFC-0010 §5). La diferencia frente al diseño
anterior es que ahora es el **único** freno: no hay presupuesto de infraestructura donde
absorber una desviación.

## 7. Fallos y degradación

| Fallo | Detección | Comportamiento |
| :--- | :--- | :--- |
| API de Anthropic caída o con timeout | Cliente del proveedor | Reintentos y fallo explícito (RFC-0013 §9). Sin *fallback* silencioso |
| Clave inválida o revocada | Arranque / primera llamada | `/readyz` en rojo. No sirve tráfico con un proveedor que no responde |
| Límite de tasa del proveedor | Respuesta 429 | Retroceso y reintento; si agota, error explícito al cliente con `degraded` registrado |
| `PROVEEDOR` desconocido | Fábrica | No arranca, listando los valores válidos (RFC-0013 §9) |
| Falta `ANTHROPIC_API_KEY` | `Settings` | No arranca (validación por rama, RFC-0013 §4) |

La caída del generador **no** coincide ya con la del embedder: son **proveedores distintos**
(RFC-0016 §9). Una caída de Anthropic deja el retrieval intacto; una de OpenAI degrada a rama
léxica sin afectar a la generación. Era imposible cuando Bedrock era ambas cosas.

## 8. Criterios de aceptación

| # | Criterio | Verificación | Aterriza en |
| :--- | :--- | :--- | :--- |
| CA-1 | `PROVEEDOR=anthropic` construye el modelo correcto y arranca sin ninguna variable `AWS_*` | `test_llm_factory.py` parametrizado + CA-2 de RFC-0016 | RFC-0018 (este PR) |
| CA-2 | `PROVEEDOR=anthropic` sin `ANTHROPIC_API_KEY` impide el arranque | `test_config.py::test_provider_required_vars` | RFC-0018 (este PR) |
| CA-3 | La suite completa de RFC-0009 se ejecuta contra este proveedor y se publica como línea base en `evals/baselines/anthropic-claude-haiku-4-5-20251001.json` — **el nombre lleva la versión**, no el alias: dos versiones distintas no pueden compartir línea base sin que una sobrescriba a la otra, que es el fallo que ADR-0012 evita | `python evals/run_eval.py --suite full --label anthropic-claude-haiku-4-5-20251001` (RFC-0013 §8: el script es la invocación canónica; `invoke evals` no reenvía `--label`) | RFC-0009 |
| CA-4 | La calibración del juez sobre los 15 casos de veredicto humano se ejecutó y publicó **antes** de usarlo como gate | Informe de calibración (RFC-0009 §4.1) | RFC-0009 |
| CA-5 | El costo medio por caso y por conversación queda dentro de RNF-5 y del umbral de RFC-0009 | `usage.cost_usd` agregado en la corrida | RFC-0009 |
| CA-6 | No queda ningún usuario IAM ni clave de AWS en el VPS | Lectura de `$RAG_CV_HOME/.env` + inventario de IAM | Despliegue en QA (operativo) |
| CA-7 | El prompt de sistema es idéntico al de cualquier otro proveedor | `git diff` sobre `app/agent/prompts.py` | RFC-0004 |
| CA-8 | El *fallback* entre proveedores sigue apagado por defecto | `test_llm_factory.py::test_fallback_disabled_by_default` | RFC-0018 (este PR) |

Cinco de los ocho criterios quedan fuera de este PR, por dos razones distintas. **CA-3, CA-4 y
CA-5** miden la corrida de evaluación, que es el entregable de RFC-0009 (punto 10 del plan de
ejecución): hasta entonces no hay conjunto dorado, ni juez, ni línea base contra la que
comparar, y el directorio `evals/` no existe. **CA-7** verifica `app/agent/prompts.py`, que no
existe hasta RFC-0004 — es el mismo caso que CA-10 de RFC-0013 (el prompt es agnóstico del
proveedor), solo que planteado desde este RFC. **CA-6** es distinto de los otros cuatro: no es
un criterio que un RFC futuro vaya a implementar y auditar, porque no hay código que lo
satisfaga. Es una acción operativa sobre una máquina que todavía no está provisionada bajo la
topología vigente (RFC-0020, punto 11 del plan, no implementado) — se ejecuta y se verifica en
el momento del despliegue a QA, con `pytest` fuera de la conversación. Los cinco se declaran
diferidos con su destino nombrado; el punto 7 entrega la configuración del proveedor
(CA-1, CA-2, CA-8), no su validación empírica ni la limpieza de una infraestructura que aún no
existe.

## 9. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| Se cambia también el modelo de generación y la evaluación deja de ser atribuible | §3: el modelo se conserva; cambiarlo exige la comparativa de RFC-0013 §8 |
| Juez y agente del mismo proveedor inflan las métricas | Calibración obligatoria con 15 veredictos humanos (CA-4) y `EVAL_JUDGE_PROVEEDOR` independiente |
| Fuga de coste sin presupuesto de infraestructura que la absorba | RNF-5 y el umbral de RFC-0009, ambos medidos por corrida (CA-5) |
| La clave de la API se filtra en un log o viaja en el despliegue | `SecretStr` (RFC-0013), `gitleaks` en CI (RFC-0008) y exclusión explícita de `.env` en la sincronización por `rsync` (RFC-0020 §6). Sin imagen, el `.dockerignore` de RFC-0015 §5 ya no es la barrera |
| Residencia de datos: los fragmentos del CV salen hacia un tercero | Declarado en ADR-0008. Reabre la decisión si aparece un requisito de cumplimiento |
| Alguien enciende el *fallback* "por si acaso" y las métricas dejan de ser comparables | CA-8 + ADR-0005, que ya lo decidió |

## 10. Estrategia de pruebas

**Unitarias.** La rama `anthropic` de la fábrica y el validador por rama de `Settings`, con las
mismas reglas de RFC-0013 §12: sin red, sin clave real, con dobles locales. CA-8 (fallback
apagado por defecto) es unitaria: se comprueba el valor por defecto de la configuración, no una
conmutación real.

**Integración.** La única de este RFC es el arranque sin ninguna variable `AWS_*` presente
(CA-1, que se apoya en CA-2 de RFC-0016). Verifica ausencia de variables, no una llamada al
proveedor.

**Evaluación.** CA-3, CA-4 y CA-5 son corridas de la suite de RFC-0009 y se ejecutan con ese
RFC. Son las que deciden si Haiku 4.5 sostiene los umbrales, y ninguna unitaria las sustituye.

Ninguna prueba automatizada de este RFC consume tokens de pago; el gasto ocurre solo en las
corridas de evaluación de RFC-0009, acotado por ADR-0012.

**CA-6 no tiene prueba automatizada, y no es un hueco de cobertura.** Verifica un estado del
VPS (ningún usuario IAM ni clave de AWS), no una propiedad del código de este repositorio; no
hay función que probar ni rama que cubrir. Se ejecuta como paso del despliegue a QA y lo
verifica el Auditor por lectura directa, igual que hoy verifica `gitleaks` o la ausencia de
secretos — una comprobación fuera de `pytest` con la misma exigibilidad que una dentro.

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla | Aterriza en |
| :--- | :--- | :--- | :--- | :--- |
| A-1 | La aplicación arranca y genera sin ninguna credencial de AWS | CA-1, CA-6 | Bloqueante | RFC-0018 (este PR) |
| A-2 | `app/providers/llm.py` sigue siendo el único módulo que menciona proveedores concretos | Lectura + `rg -n "anthropic\|bedrock" app/` | Bloqueante | RFC-0018 (este PR) |
| A-3 | `Settings` valida por rama y la clave es `SecretStr` | CA-2 + lectura | Bloqueante | RFC-0018 (este PR) |
| A-4 | El modelo designado es `claude-haiku-4-5-20251001` —la **versión con fecha**, no el alias (§3, ADR-0012)—; cualquier otro exige la comparativa de RFC-0013 §8 adjunta | Lectura del `.env` + PR | Bloqueante | RFC-0018 (este PR) |
| A-5 | Existe la línea base publicada en `evals/baselines/` | CA-3 | Bloqueante | RFC-0009 |
| A-6 | La calibración del juez se ejecutó antes de usarlo como gate | CA-4 | Mayor | RFC-0009 |
| A-7 | El *fallback* está apagado por defecto | CA-8 | Mayor | RFC-0018 (este PR) |
| A-8 | El prompt de sistema es agnóstico del proveedor | CA-7 | Mayor | RFC-0004 |
| A-9 | El usuario IAM `rag-cv-qa-invoker` fue eliminado | CA-6 | Mayor | Despliegue en QA (operativo) |
| A-10 | El costo por caso y por conversación está dentro de umbral | CA-5 | Mayor | RFC-0009 |
