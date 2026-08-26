# rag-cv

`rag-cv` es un agente conversacional que responde sobre la trayectoria profesional contenida en un CV, fundamentando cada respuesta en un corpus verificable. El repositorio está **en implementación activa** bajo la metodología ADU: ya contiene código Python en `app/` (núcleo y configuración, ingesta, recuperación híbrida, embeddings y proveedores) y migraciones de esquema con Alembic en `migrations/`. El DDL de bootstrap inicial fue **retirado** (RFC-0006 §2.2). Este README define el alcance técnico completo, cuyo destino final es AWS.

> ## Alcance vigente — leer antes que nada
>
> Este README describe el **alcance técnico completo**, cuyo destino final es AWS. El alcance
> **en ejecución hoy** es más estrecho: la PoC se entrega en **QA (VPS Ubuntu)** y AWS queda
> **diferido** — App Runner, RDS, ECR, S3, EventBridge, Secrets Manager y CloudWatch no se
> despliegan. Los embeddings corren con `text-embedding-3-small` de OpenAI y la generación por la API
> de Anthropic, y el despliegue es **nativo por SSH, sin contenedores**
> ([ADR-0010](docs/adr/ADR-0010-despliegue-nativo-sin-contenedores.md),
> [RFC-0020](docs/rfc/RFC-0020-topologia-nativa-de-qa-y-despliegue-por-ssh.md));
> **la aplicación no usa credenciales de AWS**. El CV vive como fichero en el VPS y
> sus cambios se detectan por **sondeo programado**, no por eventos de S3
> ([ADR-0009](docs/adr/ADR-0009-deteccion-de-cambios-del-corpus-por-sondeo.md),
> [RFC-0019](docs/rfc/RFC-0019-deteccion-de-cambios-del-corpus-en-el-vps.md)).
>
> Diferido **no es obsoleto**: es diseño aprobado cuya ejecución se pospone, y ningún documento de
> AWS ha sido editado. Qué está vigente y qué diferido, documento por documento, está en
> **[RFC-0016](docs/rfc/RFC-0016-alcance-poc-y-entrega-en-qa.md)**; el porqué, en
> [ADR-0006](docs/adr/ADR-0006-entorno-de-entrega-de-la-poc.md),
> [ADR-0007](docs/adr/ADR-0007-embeddings-por-api-openai.md) y
> [ADR-0008](docs/adr/ADR-0008-generacion-por-api-de-anthropic.md).
>
> Donde este README y RFC-0016 difieran sobre qué se ejecuta hoy, **prevalece RFC-0016**.

## Estado actual de la implementación

El repositorio está **en implementación activa**, una rama y un PR por RFC, bajo TDD estricto
(RFC-0014). Ya existe código Python de producción en `app/` (núcleo y configuración, ingesta,
recuperación híbrida, embeddings y proveedores) y migraciones de esquema en `migrations/`.
Quedan por construir la capa de API (RFC-0005) y la de agente Strands (RFC-0004), y por ejecutar
la evaluación (RFC-0009) y el despliegue a QA (RFC-0020, RFC-0008, RFC-0010). La capa de agente
está diseñada para usar **Strands Agents SDK** confinado a `app/agent/` (ADR-0003), y el proveedor
de generación y de embeddings se resuelve por configuración, nunca por código (ADR-0005, RNF-13).

El **orden de implementación** de los RFCs y el estado vigente/diferido de cada documento están en
[`docs/PLAN-DE-EJECUCION.md`](docs/PLAN-DE-EJECUCION.md) y en el índice de
[`docs/README.md`](docs/README.md). Este README describe el **alcance técnico completo** (destino
AWS), no el avance de cada RFC; donde este README y RFC-0016 difieran, **prevalece RFC-0016**.

## Arquitectura objetivo

### Capas y dirección de dependencias

| Capa | Responsabilidad | Depende de |
|---|---|---|
| **Domain** | Entidades, reglas de negocio y puertos: CV, fragmento, versión, consulta y resultado. | Nada externo |
| **Application** | Casos de uso: consultar CV, detectar cambio, ingerir, indexar y administrar el ciclo de vida. | Domain |
| **Adapters** | Adaptadores de entrada/salida: FastAPI, CLI, serializadores y adaptadores para puertos. | Application y Domain |
| **Infrastructure** | Implementaciones concretas: PostgreSQL/pgvector, S3, Bedrock, EventBridge, scheduler, observabilidad. | Puertos definidos por Application/Domain |

Las dependencias apuntan hacia el centro. Los casos de uso reciben interfaces (puertos) y la composición de dependencias ocurre en el borde de infraestructura. Esto mantiene testeable el núcleo y permite sustituir proveedores sin reescribir la lógica del negocio.

### Stack

- **Python** con FastAPI para la API y Strands para la orquestación del agente.
- **Modelos por configuración.** En PROD (diferido), **Amazon Bedrock**: Claude Haiku 4.5 para generación y Titan Text Embeddings V2 para embeddings. En la PoC vigente, generación por la **API de Anthropic** (`claude-haiku-4-5`) y embeddings con **`text-embedding-3-small` de OpenAI** (RFC-0017, RFC-0018).
- **PostgreSQL + pgvector** para metadatos y búsqueda vectorial; HNSW para recuperación semántica y Reciprocal Rank Fusion (RRF) para combinar señales léxicas y vectoriales.
- **AWS S3** para almacenar el CV fuente en producción.
- **PROD en AWS:** contenedor Docker en AWS App Runner, publicado desde Amazon ECR; Amazon RDS PostgreSQL con pgvector privado, conectado mediante VPC Connector y segregación de red. Las subredes privadas del conector tendrán salida obligatoria, decidida por ambiente en Terraform: NAT Gateway administrado o AWS PrivateLink/VPC endpoints, según aplique a Bedrock Runtime, S3, Secrets Manager, ECR y dependencias API. Las rutas y security groups mantendrán mínimo privilegio. Terraform declarará esta infraestructura junto con S3, Bedrock, Secrets Manager y CloudWatch.

La selección final de modelos de Bedrock, región, límites y costos se configurará por ambiente; no se codificará en los casos de uso.

## Diagramas de arquitectura y costos

La documentación técnica de arquitectura —diagramas en Mermaid (renderizados también a PNG) y la investigación de costos de producción— está en [`docs/diagramas/`](docs/diagramas/):

| Documento | Contenido |
|---|---|
| [`hoja-de-ruta.md`](docs/diagramas/hoja-de-ruta.md) | Hoja de ruta: Fases 1–4 e implementación AWS |
| [`arquitectura-c4.md`](docs/diagramas/arquitectura-c4.md) | Arquitectura C4 (Contexto, Contenedor, Componente) |
| [`arquitectura-aws.md`](docs/diagramas/arquitectura-aws.md) | Topología de producción en AWS |
| [`costos-aws.md`](docs/diagramas/costos-aws.md) | Costos mínimos de producción (≈ USD 33–60/mes) |

Para regenerar las imágenes: `pwsh -File docs/diagramas/render.ps1`.

## Fuente del CV e indexación

En producción, S3 será la fuente autoritativa de `cv.md`. El bucket debe usar versionado, cifrado SSE-KMS y acceso mínimo mediante IAM. Se habilitará la entrega de eventos a EventBridge en el bucket; la regla Object Created invocará un worker dedicado que ejecuta el caso de uso idempotente, con política de reintentos y DLQ. Un job de reconciliación programado, con cadencia configurable y propietario operativo definido, será el respaldo ante eventos perdidos o fallos transitorios.

El proceso de ingestión debe:

1. Leer el objeto y registrar `VersionId` y ETag como marcadores inmutables de origen.
2. Calcular SHA-256 del contenido descargado; el hash, no solo el ETag, confirma que el contenido cambió.
3. Comparar contra un **source ledger** persistente (versión, ETag, SHA-256, hora, estado y versión de índice), protegido por una restricción única de fuente/clave/versión, un índice de hash para detectar contenido repetido y una clave de idempotencia de job.
4. Obtener un advisory lock o lease por fuente antes de cambiar estado. Las transiciones del ledger son atómicas; los eventos duplicados detectan un estado exitoso o un job activo y terminan sin mutar datos.
5. Si cambió, fragmentar, generar embeddings, sustituir de manera transaccional los fragmentos vigentes y actualizar el ledger al finalizar. Solo el worker que mantiene el lock puede reindexar.

Las inserciones y eliminaciones normales actualizan HNSW y quedan acompañadas por el autovacuum de PostgreSQL. **No** se ejecutará `VACUUM` ni una reconstrucción HNSW por cada cambio de CV. Cuando métricas configurables y basadas en SLO —por ejemplo, porcentaje de dead tuples, bloat del índice o p95 de latencia de consulta— superen sus umbrales, se programará una ventana de mantenimiento con bloqueo serializado: `REINDEX INDEX CONCURRENTLY` (fuera de una transacción), seguido de `VACUUM ANALYZE`.

`REINDEX INDEX CONCURRENTLY` no tiene rollback transaccional. El worker de mantenimiento conservará el índice anterior hasta que el intercambio sea exitoso, monitorizará errores, reintentará o reprogramará de forma segura y, si fuera necesario, restaurará o reconstruirá el índice desde la fuente y el ledger.

## Esquema de base de datos

El esquema vive en migraciones de **Alembic** (`migrations/`), no en un script SQL de bootstrap
— ver [RFC-0006](docs/rfc/RFC-0006-modelo-de-datos-y-migraciones.md) §2.2, §4 y §5 para el
contrato completo (extensiones, `cv_chunks`, `conversations`/`messages`, el ledger
`source_documents` y `ingestion_jobs`, e índices). Aplicar con `alembic upgrade head` contra la
URL de conexión de cada ambiente; el ciclo `upgrade`/`downgrade` está probado contra una base
efímera (RFC-0006 CA-2).

## Ambientes y configuración

| Ambiente | Plataforma | Propósito | Alcance vigente |
|---|---|---|---|
| **DEV** | Windows | Desarrollo local, pruebas rápidas y configuración aislada. | Activo, ya sin credenciales de AWS |
| **QA** | VPS Linux Ubuntu | Validación de integración, despliegue y evaluación antes de liberar. | **Activo — entorno de entrega de la PoC** |
| **PROD** | Amazon AWS | Docker en App Runner desde ECR; RDS PostgreSQL/pgvector privado mediante VPC Connector, con S3, Bedrock, eventos, seguridad y observabilidad. | **Diferido** (ADR-0006) |

La configuración se resolverá por variables de entorno y secretos administrados, nunca en código ni en archivos versionados. Cada ambiente tendrá recursos, credenciales, buckets, bases de datos y permisos separados. PROD usará IAM de mínimo privilegio, KMS para cifrado, secretos administrados, registros estructurados, métricas, alarmas y trazas para API, ingestión, recuperación, costos y errores.

### Contrato planificado de telemetría y alarmas para QA/PROD

La infraestructura prevista publicará métricas y alarmas accionables en CloudWatch; los valores se parametrizarán por ambiente y se validarán antes de producción. Como línea base inicial, el equipo operará con los siguientes umbrales:

| Señal | Umbral inicial | Acción prevista |
|---|---|---|
| EventBridge o worker de ingesta | Cualquier fallo de invocación o ejecución | Alertar al responsable on-call e investigar el evento y su job. |
| DLQ | ≥1 mensaje o antigüedad del más viejo >10 min | Abrir incidente, corregir la causa y reprocesar idempotentemente. |
| Lease de ingesta | ≥1 lease vencido por más de 5 min | Alertar; liberar/reclamar con seguridad y auditar el ledger. |
| Bedrock | Throttling o errores ≥1 % durante 5 min | Investigar cuotas, reintentos y degradación; escalar si persiste. |
| Reconciliación S3 | Lag >15 min; crítico si >60 min | Ejecutar reconciliación y revisar EventBridge/worker. |
| Reindexado HNSW | Fallo inmediato o duración >30 min | Detener promoción, preservar el índice anterior y reprogramar o reconstruir desde fuente/ledger. |
| Recuperación RAG | p95 >250 ms durante 5 min o recall <0.85 en evaluación | Investigar consulta, índice, corpus y calidad antes de liberar. |
| CI | Tasa de éxito <95 % en las últimas 20 ejecuciones | Corregir la inestabilidad y bloquear la promoción hasta recuperar el objetivo. |

Para la API de producción, una tasa de errores visibles al usuario >1 % exige investigación; >2 % activa respuesta de emergencia; >5 % convoca respuesta de todas las personas responsables. Los runbooks, dashboards, propietarios y canales de alerta se crearán junto con el despliegue, no se consideran ya implementados. **Este cambio no autoriza un despliegue a PROD:** la infraestructura Terraform, las alarmas y sus pruebas de recuperación son requisitos de una entrega posterior antes de promover la aplicación.

## Instalación en producción (VPS — QA)

El manual operativo completo —orden de pasos, qué comprobar en cada salida y los fallos que no
emiten error— está en [`deploy/README.md`](deploy/README.md). Aquí, el resumen de **cómo funcionan
los dos scripts** y **cómo llega el proyecto y el CV al servidor**.

### Los dos scripts de `deploy/`

| Script | Se ejecuta | Qué hace | Cuándo |
| :--- | :--- | :--- | :--- |
| `deploy/provision.sh` | En el VPS | Aprovisiona el host: paquetes, base con ICU `es-MX`, rol de la aplicación, `enable-linger`, árbol `/opt/rag-cv`, unidad de `systemd` y sondeo del corpus | **Una vez por VPS** |
| `deploy/deploy.sh` | En tu máquina | Arma el árbol de un commit validado en verde y lo despliega como release inmutable conmutando el enlace `current` | **Cada despliegue** |

**`provision.sh`** tiene dos modos, porque separa lo que exige privilegios de lo que no
(RFC-0016 §8.1):

```bash
sudo ./provision.sh           # pasos de root: paquetes, base, rol, linger, árbol
./provision.sh --usuario      # pasos de la cuenta de operación: unidad, .env, crontab
```

Previene tres fallos que **no emiten ningún error** y por eso se verifican explícitamente: base sin
ICU `es-MX` (trocea mal los acentuados), sin `enable-linger` (el servicio no arranca tras reiniciar)
y PostgreSQL escuchando fuera del bucle local.

**`deploy.sh <sha>`** convierte el artefacto en **un commit**: `git archive <sha>` arma el árbol en un
temporal, le quita `.env`, `.git` y `corpus/`, y lo envía por `tar` sobre `ssh` a
`/opt/rag-cv/releases/<sha>/`. Después migra, conmuta el enlace `current` de forma atómica
(`mv -Tf`) y reinicia la unidad. Si el CI de ese SHA no está en verde, **aborta**.

### Cómo llega el proyecto al servidor (SSH)

No se clona el repositorio en el VPS. Lo único que se copia **a mano, una sola vez**, es la carpeta
`deploy/`, para poder ejecutar `provision.sh` allí:

```bash
scp -r deploy root@reto.qrimapp.com:/root/rag-cv-deploy
```

Todo lo demás lo envía `deploy.sh` desde tu máquina, por `tar` sobre `ssh`. La transferencia no usa
`rsync` porque no está en Git Bash de Windows: lo normativo son las propiedades —que el secreto y el
corpus no viajen, y que la conmutación sea atómica—, no la herramienta.

### Desplegar una release (SSH + git)

El despliegue corre **desde tu máquina**, no desde el VPS, y combina git y ssh: el SHA tiene que estar
committeado y con el CI en verde, y el envío se hace por ssh:

```bash
./deploy/deploy.sh <sha-validado-en-verde> qrimapp-reto@reto.qrimapp.com
```

Git no vive en el servidor: `deploy.sh` arma el árbol con `git archive <sha>` **en tu máquina** y lo
transfiere por `tar` sobre `ssh` — no se clona nada en el VPS, y no debe haber un `.git` allí. El
`<sha>` es un commit que `gh` verifica con todas sus ejecuciones de CI en `success`; sin eso, aborta.
Para desplegar sin red a sabiendas existe `SIN_CI=1`.

```bash
# Revertir a una release anterior, sin reconstruir nada:
ssh qrimapp-reto@reto.qrimapp.com \
  'ln -sfn /opt/rag-cv/releases/<sha-anterior> /opt/rag-cv/current.new && \
   mv -Tf /opt/rag-cv/current.new /opt/rag-cv/current && \
   systemctl --user restart rag-cv-api'
```

El script conserva las últimas 5 releases (`RETENCION=5`) y nunca borra la vigente.

### Cómo se copia el CV (`scp`)

El corpus **vive en el VPS y no en el repositorio** (RFC-0016 §3.3). No viaja en el despliegue a
propósito: `corpus/` se excluye del árbol, para no pisar el del VPS con el de la máquina de origen.
Se copia **a mano** con `scp` — una vez al instalar, y de nuevo cada vez que se actualice el CV:

```bash
scp corpus/cv.md qrimapp-reto@reto.qrimapp.com:/opt/rag-cv/corpus/cv.md
```

El sondeo programado de RFC-0019 detecta el cambio y reindexa sin bajar el servicio.

### Las claves de la API (`API_KEYS_JSON`)

La API exige una API Key en cada petición (RFC-0005 §6). La clave se entrega a los clientes, pero
**en el servidor solo se guarda `sha256(clave)`**, nunca la clave en claro: el valor que va en el
`.env` es el *hash*, no el secreto. Formato de la clave: `rcv_<env>_<24 caracteres aleatorios>` —
p. ej. `rcv_live_…` — y se genera una sola vez, con `secrets.token_urlsafe`:

```bash
python3 -c "import hashlib,secrets; k='rcv_live_'+secrets.token_urlsafe(18); print('clave:',k); print('hash:',hashlib.sha256(k.encode()).hexdigest())"
```

De esa salida se reparte la línea `clave:` a quien vaya a consumir la API, y se pega **solo** la
línea `hash:` (64 caracteres hexadecimales) en `API_KEYS_JSON`, dentro del `.env`:

```json
{"keys":[{"id":"demo","hash":"<sha256-de-la-clave>","role":"read","label":"demo","active":true,"expires_at":null}]}
```

Sin ninguna clave activa el proceso **no arranca** (fail fast): arrancar con la API abierta es peor
que no arrancar (CA-25, RFC-0021). Para revocar o rotar se edita el `.env` y se reinicia la unidad
(`systemctl --user restart rag-cv-api`), que en este despliegue cuesta segundos.

### La API como demonio (`systemd`)

El proceso Python no corre en una terminal: es una **unidad de usuario** de `systemd`,
`rag-cv-api.service`, instalada por `provision.sh --usuario` en `~/.config/systemd/user/` y
gestionada sin `sudo`:

```bash
systemctl --user status rag-cv-api
systemctl --user restart rag-cv-api
journalctl --user -u rag-cv-api -f
```

La unidad levanta uvicorn con dos *workers*, **solo en bucle local** y con `--proxy-headers` para que
nginx le reenvíe el cliente real:

```
/opt/rag-cv/current/.venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port 8080 --workers 2 \
    --proxy-headers --forwarded-allow-ips=127.0.0.1
```

`Restart=always` la reinicia si muere, y `WantedBy=default.target` + `enable-linger` hacen que
arranque sola tras un reinicio del host sin sesión SSH abierta. Los secretos los lee con
`EnvironmentFile=/opt/rag-cv/.env`; el `COMMIT_SHA` que publica `/readyz`, de
`current/.env.release`. El fichero de unidad declara además el endurecimiento (raíz de solo lectura,
`ProtectHome=yes`, `NoNewPrivileges=yes`, `MemoryMax=1G`), sustituto nativo de las medidas del
contenedor (RFC-0020 §5.1).

### El proxy nginx ↔ Python, y los puertos

La única forma de llegar a la API desde internet es **a través de nginx**; el resto escucha en bucle
local:

| Servicio | Escucha en | Gestionado por |
| :--- | :--- | :--- |
| nginx | `0.0.0.0:80`, `0.0.0.0:443` | `root` (panel) |
| API (uvicorn) | `127.0.0.1:8080` | `qrimapp-reto`, `systemctl --user` |
| PostgreSQL | `127.0.0.1:5432` | `root` (sistema) |

nginx hace `proxy_pass` a `127.0.0.1:8080`. La API **jamás** debe escuchar en `0.0.0.0`: eso saltaría
nginx y con él el TLS. Y en la ubicación del *stream* (`/v1/chat/stream`, `/v1/responses`) hay que
desactivar `proxy_buffering`, o nginx bufferea la respuesta y la latencia de primer token se
convierte en la de respuesta completa — el fallo silencioso de esta capa (RFC-0020 §7.1). El fragmento
completo está en [`deploy/nginx/reto.qrimapp.com.conf`](deploy/nginx/reto.qrimapp.com.conf).

### Probar los endpoints

Con `$K` = la clave en claro (`rcv_live_…`) que repartiste a los clientes. La cabecera puede ser
`X-API-Key: <clave>` o `Authorization: Bearer <clave>` (RFC-0005 §6.2).

```bash
# Salud y preparación — públicos, sin clave
curl -sS https://reto.qrimapp.com/readyz | jq
curl -sS https://reto.qrimapp.com/healthz
```

`/readyz` devuelve `status: ready`, el `commit_sha` desplegado y los tres `checks` en `ok`;
`/healthz` solo `{"status":"ok"}`.

```bash
# Turno simple (JSON)
curl -sS https://reto.qrimapp.com/v1/chat \
  -H "X-API-Key: $K" -H "Content-Type: application/json" \
  -d '{"message":"¿Qué experiencia tiene en AWS?"}'

# Streaming (SSE)
curl -N https://reto.qrimapp.com/v1/chat/stream \
  -H "X-API-Key: $K" -H "Content-Type: application/json" \
  -d '{"message":"Cuéntame un proyecto difícil"}'
```

### Open Responses: `/v1/responses`

Es el endpoint que registra una plataforma de agentes externa (Open Responses, sobre la Responses API
de OpenAI). **No es otro motor**: traduce el mismo turno de `/v1/chat` al vocabulario de la
especificación (RFC-0005 §13). El campo `model` se acepta y **se ignora** — responde el modelo
configurado, no el que pide el cliente (RFC-0013 §6).

```bash
curl -sS -X POST https://reto.qrimapp.com/v1/responses \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $K" \
  -d '{"model":"rag-cv","input":"¿Qué experiencia tiene en arquitectura de software?"}'; echo
```

Lo que recibe el cliente (`200`):

```json
{
  "id": "resp_…", "object": "response", "created_at": 1756900000,
  "status": "completed", "model": "claude-haiku-4-5-20251001",
  "output": [{
    "id": "msg_…", "type": "message", "status": "completed", "role": "assistant",
    "content": [{
      "type": "output_text",
      "text": "…",
      "annotations": [{"type":"file_citation","index":0,"file_id":"42","filename":"Banorte — …"}]
    }]
  }],
  "usage": {"input_tokens": 2140, "output_tokens": 173, "total_tokens": 2313}
}
```

- `input` acepta `string` o *array* de items; del array se toma el último mensaje `user`. Con
  `"stream": true` la respuesta es `text/event-stream` con `response.created`,
  `response.output_text.delta` y `response.completed`. `previous_response_id` continúa la conversación.
- Las citas viajan en `annotations` (`file_id` = `chunk_id`, `filename` = `unit`), y deben coincidir
  con `sources` de `/v1/chat`.
- Una abstención es un `completed` normal con `annotations` vacío: el agente dice "no consta".

```bash
# Streaming del mismo endpoint
curl -N -X POST https://reto.qrimapp.com/v1/responses \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $K" \
  -d '{"model":"rag-cv","input":"¿Qué experiencia tiene en AWS?","stream":true}'
```

La secuencia completa —aprovisionar, rellenar el `.env`, instalar nginx, desplegar, verificar y
revertir— está en [`deploy/README.md`](deploy/README.md).

## Ciclo de vida operativo

1. Un cambio en `cv.md` llega a S3 (o el scheduler detecta una discrepancia).
2. El caso de uso valida versión, ETag y SHA-256 contra el source ledger.
3. El pipeline idempotente ingiere e indexa solo si hay contenido nuevo.
4. La API consulta PostgreSQL/pgvector, combina resultados con RRF y Strands usa Bedrock para elaborar la respuesta con fuentes.
5. Métricas y alertas permiten detectar fallos, índices degradados y costos anómalos.

## Hoja de ruta

> **Diferida para el alcance vigente.** Las cuatro fases de abajo terminan en PROD sobre AWS.
> El plan que se ejecuta hoy —RFCs en orden, con sus deltas— es
> [`docs/PLAN-DE-EJECUCION.md`](docs/PLAN-DE-EJECUCION.md).

### Fase 1 — Fundaciones
- Crear la estructura Python por capas, contratos/puertos, configuración tipada y pruebas unitarias de Domain/Application.
- Definir esquema PostgreSQL/pgvector, migraciones, source ledger y evaluaciones base de recuperación.

### Fase 2 — Ingestión RAG
- Implementar lector de CV, fragmentación, embeddings de Bedrock, HNSW, RRF e ingestión idempotente local.
- Exponer casos de uso mediante FastAPI y cubrirlos con pruebas de integración deterministas para eventos S3 duplicados o fuera de orden, mismo contenido con distinto `VersionId`, contención concurrente de lock, y fallas parciales con estado atómico del job.

### Fase 3 — Entornos y AWS
- Automatizar DEV Windows y QA Ubuntu; desplegar la arquitectura PROD en AWS.
- Incorporar S3 versionado/SSE-KMS, IAM, EventBridge, scheduler de respaldo, secretos y observabilidad.

### Fase 4 — Confiabilidad operativa
- Establecer umbrales y ventana de mantenimiento para HNSW, incluyendo `REINDEX INDEX CONCURRENTLY` y `VACUUM ANALYZE`.
- Ejecutar evaluación RAG, pruebas de carga, recuperación de retry/DLQ y mantenimiento HNSW disparado por umbral, además de revisión de seguridad antes de producción.

## Criterios de aceptación principales

- El núcleo Domain/Application no importa FastAPI, AWS SDK, ORM ni drivers de base de datos.
- Un mismo SHA-256 no crea fragmentos, embeddings ni operaciones de índice duplicadas.
- Un cambio real de `cv.md` deja trazabilidad de versión/ETag/hash y actualiza los fragmentos activos de forma consistente.
- Las pruebas deterministas cubren eventos S3 duplicados/fuera de orden, contenido igual con `VersionId` distinto, contención de lock, fallo parcial con transición atómica y recuperación desde retry/DLQ.
- La política de mantenimiento HNSW se ejecuta por umbral y ventana, no por evento de actualización.
- Una prueba de operación verifica que el umbral configurado de HNSW dispara el mantenimiento serializado y recuperable.
- DEV, QA y PROD se pueden configurar y verificar independientemente, con la región AWS parametrizada.
- PROD aprovisiona una salida privada de App Runner mediante NAT Gateway o endpoints/PrivateLink, con rutas y security groups de mínimo privilegio.
- Los PR describen el área afectada, riesgo, impacto de migración/reindexado, pruebas, ambiente y rollback mediante la plantilla del repositorio.

## Contribución y revisión

Usá la plantilla en [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) para cada pull request. La plantilla hace visible qué parte de la arquitectura toca la rama y qué validar antes de aprobarla.
