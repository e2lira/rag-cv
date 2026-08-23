# RFC-0010 — Observabilidad, control de costos y operación

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0005, RFC-0007, RFC-0019 |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

Un agente puede fallar de formas que no producen un error HTTP: responde rápido, con 200, y
alucina. O responde bien pero cuesta cuatro veces más que ayer porque el modelo empezó a
encadenar herramientas. La observabilidad de un sistema LLM tiene que medir **calidad y costo**,
no solo disponibilidad y latencia.

## 2. Alcance

**Entra:** logs, trazas, métricas de negocio y de modelo, alarmas, paneles, control de costos,
retención y el runbook operativo.

**No entra:** la evaluación offline (RFC-0009), la infraestructura (RFC-0007).

## 3. Logs

- `structlog` en JSON a stdout. App Runner los envía a CloudWatch; el VPS los rota con
  `json-file` (máx. 50 MB × 3).
- Campos obligatorios en toda línea: `ts`, `level`, `event`, `request_id`, `key_id`, `env`,
  `version` (etiqueta de la imagen).
- Campos del turno: `conversation_id`, `message_id`, `model_id`, `prompt_version`,
  `tool_calls`, `retrieved`, `grounded`, `degraded`, `input_tokens`, `output_tokens`,
  `cost_usd`, `latency_ms`, `status`.
- **Redacción:** en `APP_ENV=prod` con `LOG_LEVEL=INFO`, el texto de la pregunta y de la
  respuesta **no** se escribe en el log; vive solo en la tabla `messages` (PRD §8). El log
  registra `message_len` y `answer_len`. `LOG_LEVEL=DEBUG` está prohibido en PROD por
  configuración (el arranque falla si se combina).
- Nunca se registran: API Keys, cadenas de conexión, contenido de secretos, ni el prompt de
  sistema completo (solo su versión).

## 4. Trazas

OpenTelemetry, activado si `OTEL_EXPORTER_OTLP_ENDPOINT` está definido. Strands emite
telemetría de agente que se integra en la misma traza.

Spans por turno:

```text
POST /v1/chat                       [http.route, key_id, request_id]
├── conversation.load_history       [turns, tokens]
├── agent.turn                      [model_id, prompt_version]
│   ├── tool.search_cv              [query_len, top_k, degraded]
│   │   ├── embedding.titan         [dim, latency_ms]
│   │   └── db.hybrid_search        [candidates, results, score_max]
│   └── bedrock.invoke_stream       [input_tokens, output_tokens, first_token_ms]
└── conversation.persist_turn       [cost_usd]
```

`first_token_ms` como atributo del span de Bedrock es lo que permite verificar RNF-1 sin
instrumentación adicional en el cliente.

## 5. Métricas (namespace CloudWatch `RagCV`)

| Métrica | Tipo | Dimensiones | Para qué |
| :--- | :--- | :--- | :--- |
| `Requests` | Contador | `env`, `route`, `status_code` | Tráfico y tasa de error |
| `TurnLatencyMs` | Histograma | `env`, `streaming` | RNF-2 |
| `FirstTokenMs` | Histograma | `env` | RNF-1 |
| `RetrievalLatencyMs` | Histograma | `env` | RNF-3 |
| `RetrievedChunks` | Histograma | `env` | Detecta recuperación vacía sistemática |
| `GroundedRate` | Media | `env` | Proporción de turnos con evidencia |
| `AbstentionRate` | Media | `env` | Sube de golpe si el índice se rompe |
| `ToolCallsPerTurn` | Media | `env` | Detecta encadenamiento anómalo (costo) |
| `InvalidCitations` | Contador | `env` | Señal temprana de alucinación (RFC-0009 §8.2) |
| `DegradedRetrievals` | Contador | `env`, `reason` | Fallos del proveedor de embeddings |
| `ProviderFallbacks` | Contador | `env`, `from`, `to` | Conmutaciones del Model Loop (RFC-0013 §6.1) |
| `EmbedderLatencyMs` | Histograma | `env`, `path` | Latencia del proveedor de embeddings |
| `GuardrailInterventions` | Contador | `env`, `policy` | Falsos positivos y ataques |
| `TokensIn` / `TokensOut` | Suma | `env`, `model_id` | Costo |
| `CostUsd` | Suma | `env`, `model_id` | Costo |
| `RateLimited` | Contador | `env`, `key_id` | Abuso |

Las métricas se emiten con **EMF** (Embedded Metric Format) dentro del propio log JSON: una
sola escritura produce log y métrica, sin llamadas adicionales a `PutMetricData` en la ruta
crítica.

## 6. Alarmas

| Alarma | Condición | Severidad | Acción |
| :--- | :--- | :--- | :--- |
| `ApiErrorRate` | 5xx > 2 % en 5 min | Alta | Página al responsable; revisar runbook §9.1 |
| `Availability` | `/readyz` fallando 3 veces seguidas | Alta | App Runner ya no enruta; investigar BD |
| `LatencyP95` | `TurnLatencyMs` p95 > 8 s durante 10 min | Media | Revisar Bedrock y `ToolCallsPerTurn` |
| `AbstentionSpike` | `AbstentionRate` > 0.35 en 15 min | Alta | Índice probablemente vacío o roto → runbook §9.3 |
| `InvalidCitations` | > 5 en 15 min | Media | Posible regresión del prompt → considerar reversión |
| `CostDaily` | `CostUsd` diario > USD 3 | Media | Revisar tráfico y `ToolCallsPerTurn` |
| `CostBudget` | AWS Budgets al 80 % de USD 60 | Media | Revisión de costos |
| `RateLimitedSpike` | `RateLimited` > 100 en 10 min | Media | Posible abuso; revisar `key_id` |
| `DbConnections` | Conexiones RDS > 70 % del máximo | Media | Revisar el pool |
| `DbStorage` | Espacio libre < 20 % | Media | Revisar retención |

`AbstentionSpike` merece un comentario: es la alarma que detecta el fallo silencioso más
probable de este sistema —un índice vacío tras una reindexación fallida—. El servicio sigue
devolviendo `200` y respuestas educadas diciendo que no consta nada. Sin esta alarma, el
sistema puede estar "sano" y ser inútil durante horas.

## 7. Paneles

**Panel operativo** (CloudWatch Dashboard `rag-cv-prod`):

1. Fila de salud: peticiones/min, tasa de error, p50/p95 de latencia, primer token p95.
2. Fila de calidad: `GroundedRate`, `AbstentionRate`, `InvalidCitations`, `DegradedRetrievals`.
3. Fila de costo: `CostUsd` acumulado del mes, coste medio por turno, tokens in/out.
4. Fila de dependencias: latencia de Bedrock, conexiones de RDS, errores de `throttling`.

**Informe semanal** (consulta SQL programada sobre `messages`): número de conversaciones,
turnos por conversación, tasa de abstención, preguntas más frecuentes y las 10 preguntas con
`grounded=false` — esa lista es la mejor fuente de mejoras del corpus, porque son las preguntas
reales que el CV no responde.

## 8. Control de costos

| Palanca | Mecanismo | Dónde |
| :--- | :--- | :--- |
| Tope por petición | `max_tokens=1024`, entrada ≤ 2 000 caracteres | RFC-0004, RFC-0005 |
| Tope por turno | Máx. 2 llamadas a herramientas, 4 iteraciones | RFC-0004 §8 |
| Tope por clave | 30 req/min, 1 000 req/día | RFC-0005 §7 |
| Tope por catálogo | IAM restringido a dos modelos por ARN | RFC-0007 §7.1 |
| Visibilidad | `CostUsd` por turno persistido y agregado | §5 |
| Presupuesto | AWS Budgets con alertas al 50/80/100 % | RFC-0007 §6.2 |

Cálculo del costo por turno en `app/core/pricing.py`, con la tabla de precios versionada y
fechada. Es una aproximación deliberada (los precios cambian): su valor está en detectar
**cambios relativos**, no en la exactitud contable.

## 9. Runbook

### 9.1 La API devuelve 5xx

1. `X-Request-ID` del usuario → CloudWatch Logs Insights:
   `fields @timestamp, event, error | filter request_id = "req_..."`.
2. Distinguir: ¿`upstream_unavailable` (Bedrock/BD) o `internal_error` (bug)?
3. Si es Bedrock: revisar métricas de `throttling`; si es sostenido, abrir caso de cuota.
4. Si es BD: `/readyz`, conexiones activas, espacio libre.
5. Si es bug tras un despliegue reciente: **revertir primero** (RFC-0008 §8), investigar después.

### 9.2 Latencia alta

1. Panel: ¿sube `FirstTokenMs` (Bedrock) o `RetrievalLatencyMs` (BD)?
2. Si es recuperación: comprobar que el índice HNSW existe (`\d cv_chunks`) — un `REINDEX` mal
   hecho lo puede dejar inválido — y revisar `ef_search`.
3. Si es Bedrock: comprobar `ToolCallsPerTurn`; si subió, revisar si cambió el prompt.

### 9.3 Tasa de abstención disparada

1. `SELECT count(*) FROM cv_chunks;` — si es 0 o mucho menor de lo esperado, el índice está roto.
2. Revisar `ingestion_jobs` por el último trabajo fallido y su `error`.
3. Reindexar: `POST /v1/admin/reindex {"force": true}`.
4. Si el corpus del repositorio es correcto pero la tabla no, comparar `content_hash` de una
   muestra.

### 9.4 Sospecha de alucinación reportada

1. Localizar el turno: `SELECT * FROM messages WHERE id = '<message_id>'`.
2. Revisar `source_chunk_ids` y recuperar esos fragmentos: ¿la afirmación está en ellos?
3. Si no está: añadir el caso al conjunto dorado como `abstencion` o `factual`, según
   corresponda, y abrir PR. **Todo incidente de alucinación termina en un caso de evaluación**;
   es la única forma de que no se repita.
4. Revisar `prompt_version` del turno: ¿coincide con la actual?

### 9.5 Rotación de una API Key comprometida

1. Marcar `active: false` en el secreto → efectiva en ≤ 5 min (RFC-0005 §6.1).
2. Emitir clave nueva y entregarla por canal seguro.
3. Revisar en logs el uso de la clave comprometida (`key_id`) y el costo asociado.

### 9.6 Actualización del CV

1. Editar `corpus/cv.md` en una rama; `python -m app.ingestion.indexer --dry-run` local.
2. PR: el CI ejecuta la evaluación con el corpus nuevo (puede cambiar `context recall`).
3. Merge → despliegue a QA reindexa automáticamente → revisar la evaluación de QA.
4. Promoción a PROD → `POST /v1/admin/reindex` incluido en el pipeline.

### 9.6b El proveedor de embeddings o de generación falla

**Síntoma: la tasa de abstención sube y `DegradedRetrievals` se dispara.**

1. `/readyz` indica qué dependencia está en rojo.
2. Si es el embedder: la rama léxica sigue funcionando y el servicio responde **degradado**, no
   caído. Comprobar la consola del proveedor y las cabeceras `X-RateLimit-*` en los logs.
3. Si es `ThrottlingException`: la cuota de Bedrock para ese modelo y región está saturada.
   Revisar el tráfico y, si es sostenido, abrir caso de aumento de cuota. La indexación es lo que
   más llamadas concentra (Titan no acepta lote): bajar `EMBEDDER_MAX_CONCURRENCY` como paliativo.
4. Si es `AccessDeniedException`: casi siempre es **acceso al modelo no habilitado** en esa
   cuenta y región, no la política IAM. Comprobarlo en la consola de Bedrock antes de tocar el rol.
5. Recordar que generación y embeddings comparten proveedor: si fallan los dos a la vez, es
   Bedrock, no el código.

**Síntoma: 503 en `/v1/chat` con el embedder sano.** Es el proveedor de generación.

1. Revisar `ProviderFallbacks`: si hay conmutaciones, el primario está caído y el secundario
   está sirviendo (si el fallback está activo, RFC-0013 §6.1).
2. Conmutación manual: cambiar `PROVEEDOR` y desplegar. **Antes de dejarlo así de forma
   permanente**, ejecutar la suite completa de evaluación con el proveedor nuevo (RFC-0013 §8):
   una conmutación de emergencia es aceptable durante una incidencia; adoptarla sin medir, no.

### 9.6c Cambiar el modelo de embeddings o su dimensión

Procedimiento completo en RFC-0012 §7.1. Resumen: **no es una migración de columna**. Snapshot →
recrear la columna con la dimensión nueva → recrear el índice HNSW con `CONCURRENTLY` →
`indexer --force`. Durante la reindexación la rama vectorial no funciona; la léxica sí, degradada.
Ventana de mantenimiento, nunca automático.

### 9.7 El entorno de desarrollo dejó de arrancar tras actualizar PostgreSQL (Windows)

Síntoma típico: `ERROR: could not open extension control file ... vector.control` o
`could not load library ... vector.dll`. Causa: pgvector se compila contra una versión concreta
de PostgreSQL y **no sobrevive a una actualización mayor**.

1. Confirmar: `SELECT * FROM pg_available_extensions WHERE name = 'vector';` → sin resultados.
2. Recompilar siguiendo RFC-0011 §4.2 con el `PGROOT` de la versión **nueva**.
3. `.\scripts\bootstrap-dev.ps1` para revalidar el entorno (incluye la prueba de configuración
   de texto).
4. Si la actualización cambió de versión mayor, el clúster de datos también migró: verificar
   que la base `ragcv` conserva el proveedor ICU con
   `SELECT datlocprovider, daticulocale FROM pg_database WHERE datname='ragcv';`.

Esto solo afecta a DEV. QA usa la imagen `pgvector/pgvector:pg16` y PROD usa RDS, donde la
extensión la mantiene el proveedor.

### 9.8 Restauración ante desastre

1. Infraestructura: `terraform apply` reconstruye todo excepto los datos.
2. Corpus: se reconstruye con una reindexación desde `corpus/cv.md` (no requiere respaldo).
3. Conversaciones: restaurar el último *snapshot* de RDS. Pérdida aceptada: hasta 24 h de
   historial conversacional, que no es un dato crítico.
4. Secretos: Secrets Manager tiene su propia retención; las API Keys se reemiten si es necesario.

**RTO objetivo: 1 hora. RPO objetivo: 24 h** (para conversaciones; 0 para el corpus, que vive
en Git).

## 10. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | Toda línea de log incluye `request_id`, `env` y `version` | `test_logging.py::test_mandatory_fields` |
| CA-2 | En `prod`+`INFO` el texto de pregunta y respuesta no aparece en el log | `test_logging.py::test_redaction` |
| CA-3 | `APP_ENV=prod` con `LOG_LEVEL=DEBUG` impide el arranque | `test_config.py::test_debug_forbidden_in_prod` |
| CA-4 | Las 14 métricas de §5 se emiten con las dimensiones indicadas | `test_metrics.py` |
| CA-5 | Un turno con cita inválida incrementa `InvalidCitations` | `test_metrics.py::test_invalid_citation_metric` |
| CA-6 | `cost_usd` persistido coincide con el cálculo de `pricing.py` | `test_pricing.py` |
| CA-7 | Las 10 alarmas de §6 existen en Terraform | `terraform plan` + revisión |
| CA-8 | Existe el panel `rag-cv-prod` con las cuatro filas | Inspección |
| CA-9 | Vaciar `cv_chunks` en QA dispara `AbstentionSpike` en menos de 20 min | Simulacro documentado |
| CA-10 | El trabajo de retención elimina mensajes de más de 30 días | `test_retention.py` |
| CA-11 | El runbook cubre la recompilación de pgvector en DEV tras una actualización de PostgreSQL | Simulacro documentado |
| CA-12 | Un `last_success_at` de `watcher_heartbeat` más antiguo que `WATCHER_HEARTBEAT_MAX_AGE_SECONDS` dispara alerta | Simulacro: detener el sondeo y esperar el umbral |
| CA-13 | El runbook documenta el reemplazo atómico del corpus (escribir a temporal + `mv` en el mismo sistema de ficheros) | Lectura |

**CA-12 y CA-13 llegan de RFC-0019.** Ese RFC *escribe* el latido y declara el umbral (§7.1, §7.2)
y la regla de escritura atómica (§4); *alertar* y *documentar el procedimiento* es trabajo de este.
Estaban entre sus criterios como CA-11 y A-8, lo que dejaba el gate de un RFC del punto 5
dependiendo del punto 13.

## 11. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| Fatiga de alarmas | Solo 10 alarmas, cada una con acción concreta en el runbook; sin alarmas informativas |
| Coste de CloudWatch por logs verbosos | `INFO` en PROD, retención 30 días, EMF en vez de `PutMetricData` por evento |
| Métricas verdes con calidad mala | `GroundedRate`, `InvalidCitations` e informe semanal de preguntas sin respuesta |
| Runbook desactualizado | Cada incidente exige revisar la sección correspondiente en el post-mortem |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | No se registran API Keys, secretos ni cadenas de conexión | Búsqueda en logs de prueba | Bloqueante |
| A-2 | La redacción de contenido en PROD funciona | CA-2 | Bloqueante |
| A-3 | `DEBUG` en PROD está impedido por configuración | CA-3 | Mayor |
| A-4 | Existen las métricas de calidad (`GroundedRate`, `AbstentionRate`, `InvalidCitations`) | CA-4 | Bloqueante |
| A-5 | Existe la alarma `AbstentionSpike` y se probó con un simulacro | CA-9 | Mayor |
| A-6 | `cost_usd` se persiste por turno | CA-6 | Mayor |
| A-7 | El runbook cubre todas las situaciones de §9 con pasos ejecutables, incluidas las de proveedor | Lectura | Mayor |
| A-8 | Las alarmas están en IaC, no creadas a mano | CA-7 | Mayor |
| A-9 | La emisión de métricas no añade latencia en la ruta crítica (EMF) | Lectura del código | Menor |
| A-10 | El trabajo de retención existe y está programado | CA-10 | Mayor |
| A-11 | Existe la alerta por ausencia de latido del sondeo, y mira `last_success_at`, no `last_run_at` | CA-12 | **Bloqueante** |
| A-12 | La regla de reemplazo atómico del corpus está en el runbook | CA-13 | Mayor |
