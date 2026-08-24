# RFC-0005 — API REST: contrato, autenticación por API Key y límites de uso

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0004, RFC-0006 |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

La API **es** el producto de la v1 (PRD §4): no hay interfaz propia. Debe ser consumible por un
reclutador con curl, por un frontend ajeno y por la suite de evaluación, con un contrato
estable, autenticación real y errores que no filtren nada. Y debe estar protegida frente al
abuso, porque cada petición cuesta dinero en Bedrock.

## 2. Alcance

**Entra:** endpoints, esquemas de petición/respuesta, autenticación por API Key, roles,
límites de tasa, formato de error, streaming SSE, versionado, CORS y documentación OpenAPI.

**No entra:** OAuth, registro de usuarios, multi-tenant, cuotas por plan (fuera del PRD).

## 3. Endpoints

| Método | Ruta | Auth | Descripción |
| :--- | :--- | :--- | :--- |
| `GET` | `/healthz` | No | Vivacidad. No toca dependencias. `200 {"status":"ok"}` |
| `GET` | `/readyz` | No | Preparación: BD accesible, corpus indexado, config válida |
| `POST` | `/v1/chat` | `read` | Turno de conversación, respuesta completa |
| `POST` | `/v1/chat/stream` | `read` | Turno con respuesta en streaming (SSE) |
| `POST` | `/v1/responses` | `read` | Mismo turno, en el contrato **Open Responses** (§13). Es lo que registra una plataforma de agentes externa |
| `GET` | `/v1/conversations/{id}` | `read` | Historial de una conversación (solo de la propia API Key) |
| `POST` | `/v1/admin/reindex` | `admin` | Lanza la reindexación del corpus. `202` con `job_id` |
| `GET` | `/v1/admin/jobs/{job_id}` | `admin` | Estado de una reindexación |
| `GET` | `/v1/meta` | `read` | Metadatos públicos: persona, titular, secciones, `corpus_updated_at` |
| `GET` | `/docs`, `/openapi.json` | Solo `dev`/`qa` | Documentación interactiva; **deshabilitada en PROD** |

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
  "meta": {"model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0", "prompt_version": 4,
           "degraded": false}
}
```

- `grounded` es `false` cuando la recuperación no devolvió fragmentos y la respuesta es una
  abstención. Permite al cliente —y a la evaluación— distinguir "no sé" de "sé".
- `sources` está vacío en turnos que no requirieron búsqueda; no es un error.
- `usage.cost_usd` se calcula con la tabla de precios de `app/core/pricing.py`, versionada por
  proveedor (RFC-0013).
- `meta.model_id` es el modelo **realmente usado** en ese turno, no el configurado: si el Model
  Loop conmutó por indisponibilidad, aquí se ve.

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
- Fuente de las claves: **AWS Secrets Manager** en QA y PROD (`API_KEYS_SECRET_ID`), archivo
  `.env` en DEV. Estructura del secreto:

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

- Las claves se cargan al arrancar y se refrescan cada 5 minutos en segundo plano; una
  revocación tarda como máximo ese tiempo en surtir efecto. Un fallo de refresco conserva la
  copia anterior y registra una alerta (nunca deja la API sin autenticación ni la cierra).

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

- Añadir la clave nueva al secreto → distribuir → marcar la antigua `active: false` → eliminar
  tras 7 días. Sin ventana de corte, porque conviven varias claves activas.
- Toda clave `read` emitida para el reto lleva `expires_at`; el proceso de arranque advierte de
  claves caducadas en menos de 14 días.

## 7. Límites de tasa

- Ventana deslizante por `key_id`: `RATE_LIMIT_PER_MINUTE` (30) y `RATE_LIMIT_PER_DAY` (1 000).
- Implementación: contador en PostgreSQL con `INSERT ... ON CONFLICT` sobre una tabla de
  cubetas (`rate_buckets`), suficiente para el volumen esperado y sin añadir Redis a la
  arquitectura (una pieza más que operar en tres entornos).
- Respuesta `429` con cabeceras `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
  `X-RateLimit-Reset`.
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
| 503 | `upstream_unavailable` | Bedrock o PostgreSQL no disponibles |
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
| Secrets Manager no responde al arrancar | El proceso **no arranca** (fail fast): sin claves no hay autenticación posible |
| Secrets Manager no responde al refrescar | Se conserva la copia en memoria + alerta |
| BD caída | `/readyz` en rojo, `/v1/chat` → 503; `/healthz` sigue en verde (el proceso vive) |
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
curl -sS https://api.ejemplo.com/v1/chat \
  -H "X-API-Key: $RAG_CV_KEY" -H "Content-Type: application/json" \
  -d '{"message":"¿Qué experiencia tiene en AWS?"}'

# Streaming
curl -N https://api.ejemplo.com/v1/chat/stream \
  -H "X-API-Key: $RAG_CV_KEY" -H "Content-Type: application/json" \
  -d '{"message":"Cuéntame un proyecto donde haya tomado una decisión difícil"}'

# Reindexación (admin)
curl -sS -X POST https://api.ejemplo.com/v1/admin/reindex \
  -H "X-API-Key: $RAG_CV_ADMIN_KEY" -d '{"force":false}'

# Open Responses (§13) — lo que registra una plataforma de agentes externa
curl -sS https://api.ejemplo.com/v1/responses \
  -H "Authorization: Bearer $RAG_CV_KEY" -H "Content-Type: application/json" \
  -d '{"model":"rag-cv","input":"¿Qué experiencia tiene en AWS?"}'
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

Mismo formato y códigos que §8, con una salvedad: la especificación exige un objeto de error con
`type`, `code` y `message`. Se emite ese objeto **además** del cuerpo de §8, no en su lugar, para
no romper a un cliente que ya lea el formato propio.

### 13.6 Fuera de alcance, declarado

`tools`/`tool_choice` del cliente (las herramientas las fija RFC-0004 §5), `instructions` del
cliente (el prompt de sistema es único y versionado, RFC-0004 §4), `/responses/compact`,
transporte WebSocket, y entradas de imagen. Un campo fuera de alcance **no produce error**: se
ignora en silencio, porque un `400` ante un campo opcional que la plataforma manda por defecto
haría el endpoint inservible por una razón cosmética.

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
| A-10 | El proceso no arranca si no puede cargar las API Keys en QA/PROD | Prueba de arranque con secreto inaccesible | Mayor |
| A-11 | El esquema OpenAPI generado coincide con §4 y §5 | Comparación con el contrato | Menor |
| A-12 | `/v1/responses` exige autenticación y rol `read`, como el resto de `/v1/*` | CA-15 + recorrer el router | Bloqueante |
| A-13 | `/v1/responses` **no** enruta a un modelo elegido por el cliente: el `model` de la petición se ignora (RFC-0013 §6) | CA-16 + lectura del adaptador | Bloqueante |
| A-14 | `/v1/responses` y `/v1/chat` responden desde el mismo `Agent` de `build_agent()`, sin lógica de agente duplicada | Lectura: el adaptador no llama a `build_agent` ni arma prompt propio | Mayor |
| A-15 | Las citas de `annotations` coinciden con las de `sources` para la misma pregunta | CA-17 | Mayor |
| A-16 | El límite de tasa y el tope de cuerpo se aplican a `/v1/responses` antes de invocar al agente | Orden de las dependencias en el router | Mayor |

> **Había dos filas `A-11`.** La que exigía las cinco comprobaciones invocadas en el `lifespan`
> —Bloqueante— se agregó en #30 sin verificar que el identificador estuviera libre, y convivió con
> la de OpenAPI —Menor— sobre el mismo número. Un Auditor que citara «A-11» no decía cuál de las
> dos. La del `lifespan` pasó a RFC-0021 A-1; queda la de OpenAPI, y el identificador vuelve a ser
> único.
