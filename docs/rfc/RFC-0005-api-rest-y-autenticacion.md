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
| `read` | `/v1/chat`, `/v1/chat/stream`, `/v1/conversations/{id}` (solo las propias), `/v1/meta` |
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
| CA-13 | El `lifespan` invoca **las cinco** comprobaciones de arranque de RFC-0006 §7, y una que falle impide que la aplicación quede lista | `test_startup_wiring.py`: con cada comprobación falsificada para fallar, arrancar la app aborta |

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
```

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
| A-11 | Las cinco comprobaciones de RFC-0006 §7 están **invocadas** en el `lifespan`, no solo importadas. Una comprobación que existe y nadie llama no protege ningún arranque | CA-13 + lectura del `lifespan` | Bloqueante |
| A-11 | El esquema OpenAPI generado coincide con §4 y §5 | Comparación con el contrato | Menor |
