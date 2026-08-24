# RFC-0005 — API REST: contrato, autenticación por API Key y límites de uso

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0004, RFC-0006, RFC-0013, RFC-0019, RFC-0020, RFC-0021 |
| **ADRs** | ADR-0006, ADR-0008, ADR-0012, ADR-0015, ADR-0016 |
| **Fecha** | 2026-08-22 |

> **Este documento se escribió cuando la PoC todavía iba a AWS, y el gate G2 lo rechazó por eso.**
> Cuatro defectos de fondo, corregidos en este pase: (a) **no había estrategia de pruebas** —punto 4
> del Definition of Ready— pese a que `/v1/chat` invoca al modelo y ADR-0012 prohíbe que una prueba
> automática llame a una API de pago; (b) §6.1 y §10 fijaban **AWS Secrets Manager** como fuente de
> las API Keys en QA, que RFC-0018 §4 retiró y RFC-0020 §8 sustituyó por el `.env` del VPS; (c) el
> `/readyz` de §3 no exigía el **SHA desplegado** que RFC-0020 CA-5 sí exige, y ni él ni `/healthz`
> tenían criterio; (d) `usage.cost_usd` dependía de un módulo sin criterio que lo cubriera. Las
> correcciones están marcadas en §1, §3.1, §3.2, §4, §6.1, §8, §10, §11, §12, §13.5 y §14.
>
> **La numeración no se recicla.** Las secciones nuevas son §3.1, §3.2 y §14; los criterios nuevos,
> CA-20 en adelante (CA-13 sigue retirado a RFC-0021); las comprobaciones nuevas, A-17 en adelante.

---

## 1. Contexto y problema

La API **es** el producto de la v1 (PRD §4): no hay interfaz propia. Debe ser consumible por un
reclutador con curl, por un frontend ajeno y por la suite de evaluación, con un contrato
estable, autenticación real y errores que no filtren nada. Y debe estar protegida frente al
abuso, porque cada petición cuesta dinero en la API del proveedor de generación activo (ADR-0008;
la rama concreta la resuelve `build_model`, RFC-0013 §3 — esta capa no la nombra).

## 2. Alcance

**Entra:** endpoints, esquemas de petición/respuesta, autenticación por API Key, roles,
límites de tasa, formato de error, streaming SSE, versionado, CORS y documentación OpenAPI.

**No entra:** OAuth, registro de usuarios, multi-tenant, cuotas por plan (fuera del PRD).

## 3. Endpoints

| Método | Ruta | Auth | Descripción |
| :--- | :--- | :--- | :--- |
| `GET` | `/healthz` | No | Vivacidad. No toca dependencias. `200 {"status":"ok"}` (§3.1) |
| `GET` | `/readyz` | No | Preparación: BD accesible, corpus indexado, config válida, **y el SHA desplegado** (§3.1) |
| `POST` | `/v1/chat` | `read` | Turno de conversación, respuesta completa |
| `POST` | `/v1/chat/stream` | `read` | Turno con respuesta en streaming (SSE) |
| `POST` | `/v1/responses` | `read` | Mismo turno, en el contrato **Open Responses** (§13). Es lo que registra una plataforma de agentes externa |
| `GET` | `/v1/conversations/{id}` | `read` | Historial de una conversación (solo de la propia API Key) |
| `POST` | `/v1/admin/reindex` | `admin` | Lanza la reindexación del corpus. `202` con `job_id` |
| `GET` | `/v1/admin/jobs/{job_id}` | `admin` | Estado de una reindexación |
| `GET` | `/v1/meta` | `read` | Metadatos públicos: persona, titular, secciones, `corpus_updated_at` |
| `GET` | `/docs`, `/openapi.json` | Solo `dev`/`qa` | Documentación interactiva; **deshabilitada en PROD** |

### 3.1 Contrato de `/healthz` y `/readyz`

Los dos son públicos y **la diferencia entre ellos es el punto**: `/healthz` dice si el proceso
vive, `/readyz` si puede atender. Confundirlos hace que `systemd` reinicie por una base de datos
caída, que no es un fallo del proceso.

```json
GET /healthz  →  200 {"status": "ok"}
```

No abre conexiones ni lee configuración: **sigue en `200` con PostgreSQL caído** (§10).

```json
GET /readyz  →  200
{
  "status": "ready",
  "commit_sha": "a626cf853a2bf653ebdf04be8a1ffe22062a99c0",
  "checks": {"database": "ok", "corpus_indexed": "ok", "config": "ok"}
}
```

| Campo | Contenido |
| :--- | :--- |
| `commit_sha` | **El commit desplegado.** Lo exige RFC-0020 CA-5: sin él, «desplegamos el commit X» es una afirmación de quien desplegó, no un hecho comprobable. Se lee del artefacto de la *release*, no de `git` en tiempo de ejecución: el VPS no tiene el repositorio |
| `checks.database` | Conexión válida contra PostgreSQL |
| `checks.corpus_indexed` | Hay al menos un fragmento indexado para el `doc_id` activo |
| `checks.config` | La configuración cargó y validó (RFC-0021) |

Cualquier comprobación en rojo ⇒ `503` con el mismo cuerpo y `"status": "not_ready"`, para que el
cliente sepa **cuál** falló. No es filtrado de interno (I-6): son nombres de comprobación fijos, no
trazas ni recursos.

### 3.2 Contrato de los endpoints administrativos

`/v1/admin/reindex` **encola**, no ejecuta. La ingesta la corre el proceso de RFC-0019 desde el
`crontab`; la API que atiende consultas no debe bloquearse reindexando. Ese reparto ya existe y
este endpoint se acopla a él en vez de abrir un segundo camino.

```json
POST /v1/admin/reindex        (sin cuerpo)
  →  202 {"job_id": "1f8a...", "state": "pending"}

GET /v1/admin/jobs/{job_id}
  →  200 {"job_id": "1f8a...", "state": "succeeded", "attempt_count": 1,
          "error_code": null, "started_at": "...", "completed_at": "..."}
  →  404 si no existe
```

**Es idempotente por contenido.** Forma la misma `idempotency_key` que RFC-0019 §7
(`{object_key}@{source_version_id}`) e inserta con `ON CONFLICT DO NOTHING`: pedir la reindexación
dos veces sobre el mismo corpus devuelve **el mismo `job_id`**, no encola un segundo trabajo. La
garantía no es del código de la API, es del `UNIQUE (idempotency_key)` de `ingestion_jobs`
(RFC-0006 §4).

`state` es el `job_state` de RFC-0019: `pending`, `processing`, `succeeded`, `failed` o
`dead_lettered`.

> **No hay campo `force`.** El ejemplo de §12 lo mostraba (`{"force":false}`) sin que ninguna tabla
> de contrato lo definiera, y el esquema lo hace imposible: con `idempotency_key` UNIQUE no existe
> forma de encolar un duplicado para el mismo contenido. Un campo que el esquema impide es contrato
> muerto, y un Desarrollador que intentara implementarlo chocaría con la restricción. Para volver a
> indexar contenido ya procesado, el camino es el de RFC-0019 §7 (cambiar el archivo, incluida la
> reversión a una versión anterior), no un parámetro de esta API.

## 4. Contrato de `/v1/chat`

**Petición**

```json
POST /v1/chat
X-API-Key: rcv_live_xxxxxxxxxxxxxxxxxxxxxxxx
Content-Type: application/json

{
  "message": "¿Qué experiencia tiene desplegando en AWS?",
  "conversation_id": "c1f8a0e2-...",     // opcional; si falta, se crea una nueva
  "locale": "es"                          // opcional; por defecto, se infiere del mensaje
}
```

| Campo | Tipo | Restricción |
| :--- | :--- | :--- |
| `message` | `str` | 1–2 000 caracteres, no vacío tras `strip()` |
| `conversation_id` | `uuid` \| `null` | Debe pertenecer a la misma API Key |
| `locale` | `"es"` \| `"en"` \| `null` | — |

**Respuesta `200`**

```json
{
  "conversation_id": "c1f8a0e2-...",
  "message_id": "m-9d2f...",
  "answer": "Ha desplegado servicios en AWS desde 2021 [F1], principalmente ...",
  "sources": [
    {"ref": "F1", "chunk_id": 42, "unit": "Banorte — Ingeniero de Datos Senior",
     "section": "Experiencia", "score": 0.031}
  ],
  "grounded": true,
  "usage": {"input_tokens": 2140, "output_tokens": 173, "tool_calls": 1,
            "cost_usd": 0.0091, "latency_ms": 3480},
  "meta": {"model_id": "claude-haiku-4-5-20251001", "prompt_version": 4,
           "degraded": false}
}
```

- `grounded` es `false` cuando la recuperación no devolvió fragmentos y la respuesta es una
  abstención. Permite al cliente —y a la evaluación— distinguir "no sé" de "sé".
- `sources` está vacío en turnos que no requirieron búsqueda; no es un error.
- `usage.cost_usd` se calcula con la tabla de precios de `app/core/pricing.py`, **que este punto
  crea** (hoy no existe): un diccionario por `model_id` con el precio de entrada y de salida por
  millón de tokens, y una función que lo aplica a `input_tokens`/`output_tokens`. Un `model_id`
  sin precio en la tabla ⇒ `cost_usd: null`, **nunca `0.0`**: cero afirma que el turno fue gratis,
  y `null` dice la verdad —que no se sabe— sin romper el esquema. Lo cubre **CA-22**.
- `meta.model_id` es el modelo **realmente usado** en ese turno, no el configurado: si el Model
  Loop conmutó por indisponibilidad, aquí se ve. El formato es el identificador de la rama activa
  de `build_model` (RFC-0013 §3) — con `PROVEEDOR=anthropic`, `claude-haiku-4-5-20251001`
  (ADR-0008, ADR-0012: versión con fecha, no alias).

## 5. Contrato de `/v1/chat/stream` (SSE)

Mismo cuerpo de petición. Respuesta `text/event-stream`, sin *buffering* intermedio
(`X-Accel-Buffering: no`, `Cache-Control: no-cache`).

```text
event: start
data: {"conversation_id":"c1f8a0e2-...","message_id":"m-9d2f..."}

event: tool_start
data: {"tool":"search_cv","query":"experiencia AWS"}

event: tool_end
data: {"tool":"search_cv","results":5,"latency_ms":186}

event: token
data: {"text":"Ha desplegado "}

event: sources
data: {"sources":[{"ref":"F1","chunk_id":42,"unit":"Banorte — ..."}]}

event: done
data: {"usage":{...},"grounded":true}
```

- Se envía un comentario de mantenimiento (`: ping`) cada 15 s si no hay tokens, para que los
  balanceadores no corten la conexión.
- Ante error: `event: error` con `{"error":{"code":"...","message":"..."}}` y cierre inmediato.
- El cliente puede abortar; el servidor cancela la tarea del agente y registra el turno como
  `cancelled`.

## 6. Autenticación por API Key

### 6.1 Formato y almacenamiento

- Formato: `rcv_<env>_<24 caracteres base62>`, p. ej. `rcv_live_8sK2...`. El prefijo permite
  identificar entorno y facilita el escaneo de secretos filtrados.
- **En el servidor solo se guarda `sha256(clave)`**, nunca la clave. Se genera con
  `secrets.token_urlsafe`, se muestra una única vez al crearla.
- Fuente de las claves: **el archivo `.env` del despliegue**, en todos los entornos de la PoC.
  En QA es `$RAG_CV_HOME/.env`, propiedad del usuario de servicio y con permisos `600`
  (RFC-0020 §8), excluido del `rsync` y de git. La variable es `API_KEYS_JSON` y su valor es el
  documento de abajo, en una línea.

> **Esto decía «AWS Secrets Manager en QA y PROD (`API_KEYS_SECRET_ID`)», y ya no es cierto.**
> ADR-0006 sacó AWS del alcance de la PoC, RFC-0018 §4 declara que **ningún componente llama a
> AWS**, y RFC-0020 §8 fija dónde vive el secreto en el VPS. Un Desarrollador que siguiera la
> versión anterior habría añadido `boto3` y un cliente de Secrets Manager para leer una credencial
> que está en un archivo local — y A-10 auditaba ese mecanismo retirado, así que el gate lo habría
> dado por bueno. **PROD queda fuera de alcance** (RFC-0016): cuando se reabra, su fuente de
> secretos es una decisión nueva, no la que este documento arrastraba.

```json
{
  "keys": [
    {"id": "k_recruiter_01", "hash": "9f86d0...", "role": "read",
     "label": "Reclutador Banorte", "expires_at": "2026-12-31T23:59:59Z", "active": true},
    {"id": "k_admin_01", "hash": "0a41c2...", "role": "admin",
     "label": "Operación", "expires_at": null, "active": true}
  ]
}
```

- Las claves **se cargan al arrancar y no se refrescan en caliente**: revocar una clave es editar
  el `.env` y reiniciar la unidad (`systemctl --user restart`, RFC-0020 §5), que en este despliegue
  cuesta segundos. El refresco periódico existía para no reiniciar ante un secreto remoto; con el
  secreto en un archivo local del propio host, un hilo de refresco solo añade una ventana en la que
  la copia en memoria y el archivo discrepan.

### 6.2 Verificación

- Cabecera `X-API-Key`. Se acepta también `Authorization: Bearer <clave>` por comodidad de
  clientes existentes.
- Comparación con `hmac.compare_digest` sobre el hash (tiempo constante).
- Comprobaciones: existe, `active`, no expirada, rol suficiente para la ruta.
- **Todos los fallos devuelven el mismo `401`** con cuerpo genérico: no se distingue clave
  inexistente de revocada o expirada. Distinguirlos es un oráculo para un atacante.
- El `key_id` (nunca la clave) se adjunta al contexto de log de la petición.

### 6.3 Roles

| Rol | Permisos |
| :--- | :--- |
| `read` | `/v1/chat`, `/v1/chat/stream`, `/v1/responses`, `/v1/conversations/{id}` (solo las propias), `/v1/meta` |
| `admin` | Todo lo anterior + `/v1/admin/*` |

Una conversación pertenece a la `key_id` que la creó. Otra clave que solicite ese
`conversation_id` recibe `404` (no `403`: no se confirma la existencia del recurso).

### 6.4 Rotación

- Añadir la clave nueva a `API_KEYS_JSON` → reiniciar → distribuir → marcar la antigua
  `active: false` → reiniciar → eliminarla tras 7 días. Sin ventana de corte, porque conviven
  varias claves activas.
- Toda clave `read` emitida para el reto lleva `expires_at`; el proceso de arranque advierte de
  claves caducadas en menos de 14 días.

## 7. Límites de tasa

- **Dos cubetas fijas por `key_id`** (ADR-0016): una por minuto y una por día.
- Implementación: contador en PostgreSQL con `INSERT ... ON CONFLICT` sobre `rate_buckets`
  (RFC-0006 §4.4), suficiente para el volumen esperado y sin añadir Redis a la arquitectura
  (una pieza más que operar en tres entornos).

| Elemento | Valor |
| :--- | :--- |
| Cubeta de minuto | `window_start` truncado al minuto; tope `RATE_LIMIT_PER_MINUTE` (30) |
| Cubeta de día | `window_start` truncado al día **en UTC**; tope `RATE_LIMIT_PER_DAY` (1 000) |
| Se incrementan | **Las dos, siempre**, antes de invocar al agente |
| `429` cuando | Cualquiera de las dos supera su tope |
| `Retry-After` | Segundos enteros hasta que cierre **la cubeta que disparó el rechazo**. Si son las dos, la de día: es la que sigue bloqueando después |
| `X-RateLimit-Limit` | El tope de esa misma cubeta |
| `X-RateLimit-Remaining` | `0` en el `429`; `tope - count` en una respuesta normal |
| `X-RateLimit-Reset` | Instante de cierre de esa cubeta, en segundos Unix |

> **Esta sección decía «ventana deslizante» y a la vez «tabla de cubetas», que son algoritmos
> distintos.** El esquema de RFC-0006 §4.4 —ya fusionado— fija cubetas: `PRIMARY KEY (key_id,
> window_kind, window_start)` con un contador, sin registro del instante de cada petición. La
> contradicción dejaba **CA-6 sin poder verificarse**, porque «`Retry-After` correcto» significa
> una cosa u otra según el algoritmo. Lo resuelve **ADR-0016**, que elige cubeta fija y declara la
> deuda: se toleran hasta 60 peticiones en el borde de dos minutos consecutivos, acotadas por el
> techo diario.
- Además, límite de **cuerpo de petición a 8 KB** y `message` a 2 000 caracteres: una entrada
  larga es la forma más barata de inflar el costo de tokens.

## 8. Formato de error

```json
{
  "error": {
    "code": "rate_limited",
    "message": "Has superado el límite de peticiones. Reintenta en 24 segundos.",
    "request_id": "req_01J8..."
  }
}
```

| HTTP | `code` | Cuándo |
| :--- | :--- | :--- |
| 400 | `invalid_request` | Esquema inválido, mensaje vacío o demasiado largo |
| 401 | `unauthorized` | API Key ausente, inválida, revocada o expirada |
| 403 | `forbidden` | Rol insuficiente para la ruta |
| 404 | `not_found` | Conversación inexistente o de otra clave |
| 413 | `payload_too_large` | Cuerpo > 8 KB |
| 429 | `rate_limited` | Cuota superada |
| 500 | `internal_error` | Fallo no previsto. **Mensaje genérico siempre** |
| 503 | `upstream_unavailable` | El proveedor de generación o PostgreSQL no disponibles. Se clasifica **por clase de fallo, no por SDK** (RFC-0004 §10) |
| 504 | `timeout` | El turno excedió 45 s |

`request_id` (ULID) se genera en el middleware, se devuelve en la cabecera `X-Request-ID` y
aparece en todos los logs de la petición: es el único identificador que se le pide a un usuario
para investigar un incidente. Ningún cuerpo de error contiene trazas, SQL ni nombres de
recursos internos (invariante I-6).

## 9. CORS, cabeceras y versionado

- CORS: lista blanca por `CORS_ALLOWED_ORIGINS` (vacía por defecto). La v1 no tiene frontend
  propio; abrir `*` sería regalar la clave al primero que inspeccione una página.
- Cabeceras de respuesta: `X-Request-ID`, `X-RateLimit-*`, `Cache-Control: no-store` en `/v1/*`.
- Versionado en la ruta (`/v1`). Un cambio incompatible del contrato abre `/v2`; no se rompe
  `/v1` en su sitio.
- `/docs` y `/openapi.json` se sirven solo si `APP_ENV != "prod"`.

## 10. Fallos y degradación

| Fallo | Comportamiento |
| :--- | :--- |
| `API_KEYS_JSON` ausente, vacío o con JSON inválido | El proceso **no arranca** (fail fast): sin claves no hay autenticación posible, y arrancar sin ella deja la API abierta. Lo valida el arranque de RFC-0021 |
| Ninguna clave `active` y sin expirar | El proceso **no arranca**: una API cuyo único efecto posible es `401` no está lista |
| BD caída | `/readyz` → `503` con `checks.database` en rojo, `/v1/chat` → 503; `/healthz` sigue en `200` (el proceso vive) |
| Cliente corta el SSE | Cancelación de la tarea del agente y registro del turno como `cancelled` |
| Reindexación en curso | Las lecturas siguen sirviéndose con la versión anterior (I-7) |

## 11. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | Sin `X-API-Key` → 401 con cuerpo genérico | `tests/integration/test_auth.py::test_missing_key` |
| CA-2 | Clave revocada y clave inexistente devuelven respuestas idénticas | `test_auth.py::test_no_oracle` |
| CA-3 | Rol `read` en `/v1/admin/reindex` → 403 | `test_auth.py::test_role_enforcement` |
| CA-4 | La comparación de claves usa `compare_digest` | Revisión + `test_auth.py::test_constant_time_compare` |
| CA-5 | La clave en claro no aparece en ningún log ni en la BD | `grep` sobre logs de la prueba + inspección de esquema |
| CA-6 | Superar la cuota devuelve 429 con `Retry-After` correcto | `test_rate_limit.py` |
| CA-7 | Cuerpo > 8 KB → 413 antes de tocar el agente | `test_limits.py::test_payload_too_large` |
| CA-8 | Una conversación de otra clave devuelve 404, no 403 | `test_auth.py::test_conversation_isolation` |
| CA-9 | Un 500 provocado no expone traza ni SQL | `test_errors.py::test_no_internal_leak` |
| CA-10 | `/docs` devuelve 404 con `APP_ENV=prod` | `test_docs_disabled.py` |
| CA-11 | El flujo SSE emite `start`, ≥1 `token`, `sources`, `done` en orden | `test_stream.py::test_event_order` |
| CA-12 | `X-Request-ID` aparece en la respuesta y en todas las líneas de log del turno | `test_observability.py` |
| CA-14 | `POST /v1/responses` con `{"model","input"}` devuelve un objeto `response` con `output[0].content[0].type == "output_text"` y `status == "completed"` | `tests/integration/test_responses_api.py::test_minimal_contract` |
| CA-15 | `Authorization: Bearer <clave>` autentica `/v1/responses`; sin cabecera → 401 con el mismo cuerpo genérico que CA-1 | `test_responses_api.py::test_auth_bearer` |
| CA-16 | El `model` de la petición se ignora y la respuesta reporta el modelo **realmente usado** (§13.2) | `test_responses_api.py::test_model_is_reported_not_honoured` |
| CA-17 | Las citas viajan en `output[0].content[0].annotations`, con el mismo `chunk_id` que `sources` de §4 para la misma pregunta | `test_responses_api.py::test_annotations_match_sources` |
| CA-18 | Con `"stream": true` la respuesta es `text/event-stream` y emite `response.output_text.delta` ≥1 vez y `response.completed` al final | `test_responses_api.py::test_stream_event_order` |
| CA-19 | `previous_response_id` continúa la conversación: el segundo turno ve el primero | `test_responses_api.py::test_conversation_continuity` |
| CA-20 | `/readyz` devuelve `commit_sha` igual al SHA de la *release* desplegada, y `503` con la comprobación en rojo cuando PostgreSQL no responde | `tests/integration/test_health.py::test_readyz_reports_commit_and_checks` |
| CA-21 | `/healthz` sigue en `200` con PostgreSQL caído (no abre conexiones) | `test_health.py::test_healthz_survives_db_outage` |
| CA-22 | `usage.cost_usd` aplica la tabla de `app/core/pricing.py` a los tokens del turno, y es `null` —no `0.0`— para un `model_id` sin precio | `tests/unit/test_pricing.py::test_cost_from_token_counts`, `::test_unknown_model_is_null` |
| CA-23 | El cuerpo de error de `/v1/responses` lleva **ambas** formas: la de §8 y el objeto de §13.5, en la misma respuesta | `test_responses_api.py::test_error_body_carries_both_shapes` |
| CA-24 | `POST /v1/admin/reindex` dos veces sobre el mismo corpus devuelve el mismo `job_id` y deja **una sola** fila en `ingestion_jobs` | `tests/integration/test_admin.py::test_reindex_is_idempotent` |
| CA-25 | El proceso no arranca si `API_KEYS_JSON` falta, es inválido o no tiene ninguna clave activa | `tests/unit/test_api_keys_loading.py` |

> **CA-13 se movió a RFC-0021.** Exigía que el `lifespan` invocara las cinco comprobaciones de
> RFC-0006 §7. Alojarlo aquí lo dejaba detrás de la capa de agente —este RFC declara `Depende de:
> RFC-0004`, superseded en cadena por RFC-0013 y RFC-0018— mientras la protección no existía. Y
> contradecía a RFC-0011 CA-4, que exige que arrancar con el CLI de `uvicorn` dé un error de bucle
> de eventos «no un error de base de datos». RFC-0021 lo resuelve separando los dos puntos de
> entrada. El `/readyz` con contrato real (§3, incluida la comprobación 6 de RFC-0006 §7) sigue
> siendo de este RFC.

## 12. Ejemplos de uso

```bash
# Turno simple
curl -sS https://reto.qrimapp.com/v1/chat \
  -H "X-API-Key: $RAG_CV_KEY" -H "Content-Type: application/json" \
  -d '{"message":"¿Qué experiencia tiene en AWS?"}'

# Streaming
curl -N https://reto.qrimapp.com/v1/chat/stream \
  -H "X-API-Key: $RAG_CV_KEY" -H "Content-Type: application/json" \
  -d '{"message":"Cuéntame un proyecto donde haya tomado una decisión difícil"}'

# Reindexación (admin) — sin cuerpo, idempotente por contenido (§3.2)
curl -sS -X POST https://reto.qrimapp.com/v1/admin/reindex \
  -H "X-API-Key: $RAG_CV_ADMIN_KEY"

# Open Responses (§13) — lo que registra una plataforma de agentes externa
curl -sS https://reto.qrimapp.com/v1/responses \
  -H "Authorization: Bearer $RAG_CV_KEY" -H "Content-Type: application/json" \
  -d '{"model":"rag-cv","input":"¿Qué experiencia tiene en AWS?"}'

# Identidad del despliegue (§3.1) — público, sin clave
curl -sS https://reto.qrimapp.com/readyz
```

## 13. Contrato Open Responses (`POST /v1/responses`)

Una plataforma de agentes externa registra este servicio dando **la URL pública del endpoint y
una API Key**, y luego conversa con él. El protocolo que espera es
[Open Responses](https://www.openresponses.org/specification) — la especificación abierta
construida sobre la Responses API de OpenAI, donde la generación vive en `POST /v1/responses`.

**Esto no es un segundo agente ni un segundo motor.** Es un **adaptador de transporte** sobre el
mismo `Agent` que construye `build_agent()` y que sirve a §4 y §5 (RFC-0004 §6) — construido una
sola vez por proceso en el `lifespan`, con el historial pasado por invocación (RFC-0004 §6, §7).
Cualquier diferencia de comportamiento entre
`/v1/chat` y `/v1/responses` para la misma pregunta es un defecto, no una variante.

### 13.1 Petición

```json
POST /v1/responses
Authorization: Bearer rcv_live_xxxxxxxxxxxxxxxxxxxxxxxx
Content-Type: application/json

{
  "model": "rag-cv",
  "input": "¿Qué experiencia tiene desplegando en AWS?",
  "stream": false,
  "previous_response_id": "resp_9d2f..."
}
```

| Campo | Tipo | Tratamiento |
| :--- | :--- | :--- |
| `model` | `str` | **Se acepta y se ignora su valor.** Ver §13.2 |
| `input` | `str` \| `array` | Obligatorio. Como `str`, es el mensaje del turno. Como *array* de *items*, se toma el último `message` de rol `user`; las mismas restricciones de `message` en §4 (1–2 000 caracteres) |
| `stream` | `bool` | Por defecto `false`. Con `true`, §13.4 |
| `previous_response_id` | `str` \| `null` | Continúa la conversación. Mapea al `conversation_id` de §4, con el mismo aislamiento por `key_id` de §6.3 |
| `instructions`, `tools`, `tool_choice`, `truncation`, `service_tier` | — | **Fuera de alcance.** Se aceptan sin error y se ignoran: el prompt de sistema y las herramientas los fija RFC-0004, no el cliente |

**Autenticación:** cabecera `Authorization`, ya soportada por §6.2 sin cambios. Rol `read`,
límites de tasa de §7 y tope de cuerpo de 8 KB idénticos al resto de `/v1/*`.

### 13.2 Por qué `model` se ignora en lugar de rechazarse

El campo es obligatorio en la especificación, así que la plataforma **siempre** mandará algo. Hay
tres tratamientos posibles y dos son incorrectos:

| Tratamiento | Por qué no |
| :--- | :--- |
| Honrar el valor y enrutar a ese modelo | Es enrutado dinámico por petición, que **RFC-0013 §6 prohíbe explícitamente**: rompe la comparabilidad de las métricas de RFC-0009, la reproducibilidad de incidentes y la previsibilidad del coste (RNF-5) |
| Rechazar con `400` si no coincide con el configurado | La plataforma no puede conocer nuestro identificador interno antes de registrarnos. Un `400` en el primer contacto hace el endpoint inservible |
| **Aceptar, ignorar, y reportar el real** (elegido) | Cumple la especificación sin mentir: el `model` de la respuesta es el que de verdad generó el turno, exactamente lo que `meta.model_id` ya hace en §4 |

La respuesta **nunca devuelve el `model` que el cliente pidió**. Devuelve el que se usó. Un cliente
que compare ambos ve la diferencia y sabe a qué atenerse; devolverle su propio valor sería
afirmar algo falso sobre qué modelo respondió.

### 13.3 Respuesta `200` (sin *streaming*)

```json
{
  "id": "resp_9d2f...",
  "object": "response",
  "created_at": 1756900000,
  "status": "completed",
  "model": "claude-haiku-4-5-20251001",
  "output": [
    {
      "id": "msg_4a7c...",
      "type": "message",
      "status": "completed",
      "role": "assistant",
      "content": [
        {
          "type": "output_text",
          "text": "Ha desplegado servicios en AWS desde 2021 [F1], principalmente ...",
          "annotations": [
            {"type": "file_citation", "index": 0, "file_id": "42",
             "filename": "Banorte — Ingeniero de Datos Senior"}
          ]
        }
      ]
    }
  ],
  "usage": {"input_tokens": 2140, "output_tokens": 173, "total_tokens": 2313}
}
```

- `status` es `"completed"` en un turno normal e `"incomplete"` si se agotó el límite de
  ejecución de RFC-0004 §8.
- **`annotations` transporta las citas.** Es el único campo del contrato donde caben, y mantiene
  la trazabilidad que §4 publica en `sources`: `file_id` lleva el `chunk_id` y `filename` la
  `unit`. CA-17 exige que coincidan con `sources` para la misma pregunta — si divergen, una de
  las dos superficies está mintiendo sobre de dónde salió la respuesta.
- Una **abstención** (`grounded: false` en §4) es una respuesta `completed` normal con
  `annotations` vacío. No es un error: el agente sabe decir "no consta".
- `usage` no incluye `cost_usd`: no es parte del contrato Open Responses. Se sigue registrando
  internamente (RFC-0010) y en `/v1/chat`.

### 13.4 *Streaming* (`"stream": true`)

`Content-Type: text/event-stream`, con las mismas cabeceras anti-*buffering* de §5. Los nombres de
evento son los de Open Responses, **no** los de §5:

```text
data: {"type":"response.created","response":{"id":"resp_9d2f...","status":"in_progress"}}

data: {"type":"response.output_text.delta","sequence_number":1,"item_id":"msg_4a7c...","output_index":0,"content_index":0,"delta":"Ha desplegado "}

data: {"type":"response.completed","response":{"id":"resp_9d2f...","status":"completed","output":[...],"usage":{...}}}
```

`response.completed` carga el objeto completo de §13.3, para que un cliente que solo escuche ese
evento tenga la respuesta entera con sus `annotations`.

### 13.5 Errores

Mismos códigos HTTP que §8. La especificación exige un objeto de error con `type`, `code` y
`message`; se emite **además** del cuerpo de §8, no en su lugar, para no romper a un cliente que ya
lea el formato propio. Las dos formas conviven como claves hermanas del mismo objeto:

```json
{
  "error": {
    "code": "rate_limited",
    "message": "Has superado el límite de peticiones. Reintenta en 24 segundos.",
    "request_id": "req_01J8..."
  },
  "type": "error",
  "code": "rate_limited",
  "message": "Has superado el límite de peticiones. Reintenta en 24 segundos."
}
```

`code` y `message` se **duplican** a propósito: son el mismo valor en los dos sitios, así que un
cliente que lea cualquiera de las dos formas obtiene lo mismo. `request_id` vive solo en `error`,
porque no pertenece a la especificación. Lo cubre **CA-23**.

> **Esto antes decía solo «se emite ese objeto además del cuerpo de §8».** No mostraba la forma
> resultante ni tenía criterio, así que admitía al menos tres implementaciones distintas —anidado,
> hermano, o sustituyendo— y ninguna era comprobable. Un contrato que admite tres lecturas no es un
> contrato (RFC-0014 §1).

### 13.6 Fuera de alcance, declarado

`tools`/`tool_choice` del cliente (las herramientas las fija RFC-0004 §5), `instructions` del
cliente (el prompt de sistema es único y versionado, RFC-0004 §4), `/responses/compact`,
transporte WebSocket, y entradas de imagen. Un campo fuera de alcance **no produce error**: se
ignora en silencio, porque un `400` ante un campo opcional que la plataforma manda por defecto
haría el endpoint inservible por una razón cosmética.

## 14. Estrategia de pruebas

**Ninguna prueba automática de este RFC llama a una API de pago** (ADR-0012). Es la sección que
faltaba, y no es un trámite: `/v1/chat`, `/v1/chat/stream` y `/v1/responses` invocan al agente, que
invoca al modelo. Sin decir dónde se corta esa cadena, la primera prueba de la API gasta dinero en
cada `invoke test`, en cada *push* y en los dos *jobs* de CI.

**Dónde se corta: en el modelo, no en el agente.** Las pruebas sustituyen el modelo por el
`ScriptedModel` de RFC-0004 §12 —guion fijo de eventos— y dejan intacto el resto del camino: router,
autenticación, límites, el `Agent` real de `build_agent()`, la memoria y la serialización SSE. Doblar
el agente entero probaría el doble, no la API (P-2).

| Nivel | Marcador | Qué cubre | Qué usa |
| :--- | :--- | :--- | :--- |
| Unitarias | `-m unit` | Validación de esquemas de petición, formato de error (§8), verificación de API Key y roles (§6), tabla de precios (§4, CA-22), carga de `API_KEYS_JSON` (CA-25), `/docs` deshabilitado, CORS | Sin BD, sin red, sin modelo |
| Integración | `-m integration` | El turno completo extremo a extremo: límite de tasa sobre `rate_buckets`, aislamiento de conversaciones por `key_id`, persistencia del turno, `/readyz`, orden de eventos SSE, encolado idempotente de reindexación | PostgreSQL efímero (`TEST_DB_MODE`) + `ScriptedModel` |

Reglas que este RFC hereda y conviene tener presentes al escribir sus pruebas:

- **El orden de los eventos SSE se afirma sobre el flujo recibido, nunca sobre tiempos.** Nada de
  `time.sleep()` para "esperar a que llegue" (P-7): produce intermitencia y se acaba desactivando.
- **Las aserciones son sobre el contrato, no sobre el texto del modelo** (P-4). Que `sources` llegue
  antes que `done`, que `annotations` lleve el `chunk_id` correcto, que un `429` traiga
  `Retry-After`: todo eso es determinista. Qué palabras responde el agente, no — eso es RFC-0009.
- **Las claves de prueba son claves de prueba.** Ninguna prueba contiene una clave con el prefijo
  `rcv_live_`; el CI no tiene credenciales de ningún proveedor y no se le añaden (ADR-0012).

**Lo que NO se prueba aquí:** la calidad de la respuesta y la resistencia adversarial son de
RFC-0009 (§5 y ADR-0015); el despliegue y el `commit_sha` real de `/readyz` en el VPS los verifica
RFC-0020 CA-5. Aquí se prueba que el campo existe y se sirve, no que el host esté bien desplegado.

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | En la BD y en los secretos solo hay hashes, nunca claves en claro | Inspección de esquema y del secreto | Bloqueante |
| A-2 | La comparación es de tiempo constante | CA-4 | Mayor |
| A-3 | 401 no distingue entre causas | CA-2 | Mayor |
| A-4 | Todas las rutas `/v1/*` exigen autenticación; `/healthz` y `/readyz` no | Recorrer el router | Bloqueante |
| A-5 | Los errores no filtran internos (I-6) | CA-9 | Bloqueante |
| A-6 | El límite de tasa se aplica antes de invocar al agente | Orden de las dependencias en el router | Mayor |
| A-7 | `/docs` deshabilitado en PROD | CA-10 | Mayor |
| A-8 | CORS no está en `*` | Lectura de la configuración del middleware | Bloqueante |
| A-9 | El aislamiento de conversaciones por `key_id` está probado | CA-8 | Bloqueante |
| A-10 | El proceso no arranca si no puede cargar las API Keys del `.env` (ausente, inválido o sin clave activa) | CA-25 | Mayor |
| A-11 | El esquema OpenAPI generado coincide con §4 y §5 | Comparación con el contrato | Menor |
| A-12 | `/v1/responses` exige autenticación y rol `read`, como el resto de `/v1/*` | CA-15 + recorrer el router | Bloqueante |
| A-13 | `/v1/responses` **no** enruta a un modelo elegido por el cliente: el `model` de la petición se ignora (RFC-0013 §6) | CA-16 + lectura del adaptador | Bloqueante |
| A-14 | `/v1/responses` y `/v1/chat` responden desde el mismo `Agent` de `build_agent()`, sin lógica de agente duplicada | Lectura: el adaptador no llama a `build_agent` ni arma prompt propio | Mayor |
| A-15 | Las citas de `annotations` coinciden con las de `sources` para la misma pregunta | CA-17 | Mayor |
| A-16 | El límite de tasa y el tope de cuerpo se aplican a `/v1/responses` antes de invocar al agente | Orden de las dependencias en el router | Mayor |
| A-17 | **Ninguna prueba automática llama a una API de pago** (ADR-0012): el modelo se dobla siempre con el `ScriptedModel` de RFC-0004 §12, y ninguna prueba trae una clave `rcv_live_` ni una clave de proveedor | `grep` sobre `tests/` + revisión de los marcadores usados contra `pyproject.toml` | Bloqueante |
| A-18 | **`app/` no lee ningún secreto de AWS**: no hay cliente de Secrets Manager ni `API_KEYS_SECRET_ID` | `rg -n "secretsmanager\|boto3\|API_KEYS_SECRET_ID" app/` sin resultados | Bloqueante |
| A-19 | `/readyz` expone el `commit_sha` de la *release* y devuelve `503` con la comprobación en rojo; `/healthz` no abre conexiones | CA-20, CA-21 | Mayor |
| A-20 | `usage.cost_usd` es `null` —no `0.0`— para un `model_id` sin precio en la tabla | CA-22 | Mayor |
| A-21 | `/v1/admin/reindex` **encola** y no ejecuta la ingesta en el proceso de la API, y es idempotente por `idempotency_key` | CA-24 + lectura del *handler* | Mayor |

> **Había dos filas `A-11`.** La que exigía las cinco comprobaciones invocadas en el `lifespan`
> —Bloqueante— se agregó en #30 sin verificar que el identificador estuviera libre, y convivió con
> la de OpenAPI —Menor— sobre el mismo número. Un Auditor que citara «A-11» no decía cuál de las
> dos. La del `lifespan` pasó a RFC-0021 A-1; queda la de OpenAPI, y el identificador vuelve a ser
> único.
