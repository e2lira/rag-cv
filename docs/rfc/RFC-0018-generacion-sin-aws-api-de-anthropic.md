# RFC-0018 — Generación sin AWS: API de Anthropic

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0013, RFC-0009, RFC-0016 |
| **Supersede** | RFC-0013 §5 (valor por defecto de `PROVEEDOR`); RFC-0007 §5.2 (credenciales de AWS en QA), que queda **derogado** para la PoC |
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
  y `ANTHROPIC_MODEL_ID` (RFC-0013 §5).
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
| `PROVEEDOR` | `anthropic` | Sustituye al `bedrock` por defecto de RFC-0013 §5 |
| `ANTHROPIC_MODEL_ID` | `claude-haiku-4-5` | **El mismo modelo** que designaba ADR-0005; cambia el camino, no el modelo |
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
- El secreto de larga vida de la PoC pasa a ser **uno solo**: `ANTHROPIC_API_KEY`.

Se declara sin adornos: RNF-8 se sigue cumpliendo —el secreto no vive en el repositorio— pero se
pierde el "cero claves" que el rol de instancia daba en el PROD diferido. Es un secreto menos que
antes y uno más que en el diseño de PROD.

Y hay un segundo matiz que no conviene callar: sin usuario de servicio sin shell (RFC-0016 §8.1),
quien entre por SSH con la cuenta de despliegue **lee ese secreto**. Los permisos `600` protegen
frente a otras cuentas del host, no frente a la propia. Es el precio de no tener privilegios de
administrador, y se acota con acceso por clave y sin contraseña (RFC-0007 §5.1).

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
| API de Anthropic caída o con timeout | Cliente del proveedor | Reintentos y fallo explícito (RFC-0013 §7). Sin *fallback* silencioso |
| Clave inválida o revocada | Arranque / primera llamada | `/readyz` en rojo. No sirve tráfico con un proveedor que no responde |
| Límite de tasa del proveedor | Respuesta 429 | Retroceso y reintento; si agota, error explícito al cliente con `degraded` registrado |
| `PROVEEDOR` desconocido | Fábrica | No arranca, listando los valores válidos (RFC-0013 §7) |
| Falta `ANTHROPIC_API_KEY` | `Settings` | No arranca (validación por rama, RFC-0013 §5) |

La caída del generador **no** coincide ya con la del embedder: son sistemas independientes
(RFC-0016 §9). Una caída de la API de Anthropic deja el retrieval intacto; una caída de `ollama`
degrada a rama léxica sin afectar a la generación.

## 8. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | `PROVEEDOR=anthropic` construye el modelo correcto y arranca sin ninguna variable `AWS_*` | `test_llm_factory.py` parametrizado + CA-2 de RFC-0016 |
| CA-2 | `PROVEEDOR=anthropic` sin `ANTHROPIC_API_KEY` impide el arranque | `test_config.py::test_provider_required_vars` |
| CA-3 | La suite completa de RFC-0009 se ejecuta contra este proveedor y se publica como línea base en `evals/baselines/anthropic-claude-haiku-4-5.json` | `invoke evals --suite full` |
| CA-4 | La calibración del juez sobre los 15 casos de veredicto humano se ejecutó y publicó **antes** de usarlo como gate | Informe de calibración (RFC-0009 §4.1) |
| CA-5 | El costo medio por caso y por conversación queda dentro de RNF-5 y del umbral de RFC-0009 | `usage.cost_usd` agregado en la corrida |
| CA-6 | No queda ningún usuario IAM ni clave de AWS en el VPS | Lectura de `$RAG_CV_HOME/.env` + inventario de IAM |
| CA-7 | El prompt de sistema es idéntico al de cualquier otro proveedor | `git diff` sobre `app/agent/prompts.py` |
| CA-8 | El *fallback* entre proveedores sigue apagado por defecto | `test_llm_factory.py::test_fallback_disabled_by_default` |

## 9. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| Se cambia también el modelo de generación y la evaluación deja de ser atribuible | §3: el modelo se conserva; cambiarlo exige la comparativa de RFC-0013 §8 |
| Juez y agente del mismo proveedor inflan las métricas | Calibración obligatoria con 15 veredictos humanos (CA-4) y `EVAL_JUDGE_PROVEEDOR` independiente |
| Fuga de coste sin presupuesto de infraestructura que la absorba | RNF-5 y el umbral de RFC-0009, ambos medidos por corrida (CA-5) |
| La clave de la API se filtra en un log o en la imagen | `SecretStr` (RFC-0013), `.dockerignore` (RFC-0015 §5), `gitleaks` en CI (RFC-0008) |
| Residencia de datos: los fragmentos del CV salen hacia un tercero | Declarado en ADR-0008. Reabre la decisión si aparece un requisito de cumplimiento |
| Alguien enciende el *fallback* "por si acaso" y las métricas dejan de ser comparables | CA-8 + ADR-0005, que ya lo decidió |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | La aplicación arranca y genera sin ninguna credencial de AWS | CA-1, CA-6 | Bloqueante |
| A-2 | `app/providers/llm.py` sigue siendo el único módulo que menciona proveedores concretos | Lectura + `rg -n "anthropic\|bedrock" app/` | Bloqueante |
| A-3 | `Settings` valida por rama y la clave es `SecretStr` | CA-2 + lectura | Bloqueante |
| A-4 | El modelo designado es `claude-haiku-4-5`; cualquier otro exige la comparativa de RFC-0013 §8 adjunta | Lectura del `.env` + PR | Bloqueante |
| A-5 | Existe la línea base publicada en `evals/baselines/` | CA-3 | Bloqueante |
| A-6 | La calibración del juez se ejecutó antes de usarlo como gate | CA-4 | Mayor |
| A-7 | El *fallback* está apagado por defecto | CA-8 | Mayor |
| A-8 | El prompt de sistema es agnóstico del proveedor | CA-7 | Mayor |
| A-9 | El usuario IAM `rag-cv-qa-invoker` fue eliminado | CA-6 | Mayor |
| A-10 | El costo por caso y por conversación está dentro de umbral | CA-5 | Mayor |
