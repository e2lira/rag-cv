# rag-cv

`rag-cv` será un agente conversacional que responde sobre la trayectoria profesional contenida en un CV. El repositorio está **en fase de planificación y arquitectura**: aún no contiene la aplicación Python ni un framework de migraciones o pipeline de indexación; sí incluye DDL inicial de bootstrap PostgreSQL para QA y PROD. Este README define el alcance técnico que se implementará.

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

## Estado y resultado de la auditoría

La propuesta es viable con algunos ajustes obligatorios antes de construir:

- Aplicar SOLID y Clean Architecture desde el primer caso de uso; no acoplar la lógica del CV, RAG ni Bedrock a FastAPI, SQLAlchemy o AWS.
- Tratar S3 como fuente autoritativa del CV en producción y conservar una trazabilidad de la versión que produjo cada índice.
- Reindexar de forma idempotente cuando cambie el contenido real del CV; una actualización normal del índice HNSW no equivale a ejecutar `VACUUM` o reconstruirlo.
- La línea base aceptada es `us-east-2` (ADR-0005). Terraform y variables de entorno deben mantener región, IAM, red y perfil de inferencia alineados por ambiente; los ejemplos antiguos que citan `us-east-1` deben normalizarse, no interpretarse como una segunda decisión vigente.

### Verificación: Python, Strands Agents y Amazon Bedrock

La arquitectura **sí los contempla**, pero no están implementados todavía: el repositorio no contiene código Python. La evidencia de diseño es la [ADR-0003](docs/adr/ADR-0003-framework-de-agente.md), aceptada, que define **Strands Agents SDK** y `BedrockModel`, confinados al adaptador `app/agent/`; y la [ADR-0005](docs/adr/ADR-0005-proveedor-de-generacion.md), que establece Bedrock como proveedor inicial por configuración. La conversación de referencia también describe el despliegue Python + Strands + Bedrock.

Esto conserva Clean Architecture: Domain y Application declaran puertos para generación, embeddings y recuperación; el adaptador de infraestructura usa Strands y Amazon Bedrock. La futura fábrica de proveedores no autoriza que los casos de uso dependan del SDK ni de `boto3`. Para PROD, Bedrock será la configuración base y se accederá mediante el rol IAM; cualquier cambio de proveedor requerirá evaluación y aprobación explícitas.

## Arquitectura objetivo

### Capas y dirección de dependencias

| Capa | Responsabilidad | Depende de |
|---|---|---|
| **Domain** | Entidades, reglas de negocio y puertos: CV, fragmento, versión, consulta y resultado. | Nada externo |
| **Application** | Casos de uso: consultar CV, detectar cambio, ingerir, indexar y administrar el ciclo de vida. | Domain |
| **Adapters** | Adaptadores de entrada/salida: FastAPI, CLI, serializadores y adaptadores para puertos. | Application y Domain |
| **Infrastructure** | Implementaciones concretas: PostgreSQL/pgvector, S3, Bedrock, EventBridge, scheduler, observabilidad. | Puertos definidos por Application/Domain |

Las dependencias apuntan hacia el centro. Los casos de uso reciben interfaces (puertos) y la composición de dependencias ocurre en el borde de infraestructura. Esto mantiene testeable el núcleo y permite sustituir proveedores sin reescribir la lógica del negocio.

### Stack previsto

- **Python** con FastAPI para la API y Strands para la orquestación del agente.
- **Amazon Bedrock** para los modelos generativos y de embeddings definidos en la conversación de arquitectura AWS.
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

## Esquema de base de datos para QA y PROD

El DDL inicial está en [`infra/sql/001_initialize_rag_cv.sql`](infra/sql/001_initialize_rag_cv.sql). Crea de forma aditiva el esquema `rag_cv`, las extensiones `vector`/`pgcrypto`, el **source ledger**, el ledger de trabajos idempotentes, los chunks con `vector(1024)` para Amazon Titan Text Embeddings V2 y los índices relacionales, FTS y HNSW necesarios. No ejecuta `VACUUM` ni `REINDEX` automático; incluye una eliminación protegida de una restricción única obsoleta, sin borrar datos, para que cada `VersionId` permanezca auditable aunque su contenido no cambie.

### Ejecución segura

1. Aprovisionar PostgreSQL con **pgvector** disponible y crear una identidad de migración con permiso para `CREATE EXTENSION`, esquema, tablas, funciones e índices. La identidad de aplicación debe recibir después solo permisos mínimos de `USAGE`/DML.
2. Ejecutar, por separado y con URL de conexión de cada ambiente: `psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/001_initialize_rag_cv.sql`.
3. Verificar las extensiones y objetos creados, y otorgar permisos a la identidad runtime según los adaptadores que se implementen. Ejecutar el script repetidamente es seguro para el bootstrap; cambios posteriores deben ser migraciones aditivas y compatibles hacia atrás.

El modelo de datos bloquea eventos duplicados con claves únicas de `(object_key, s3_version_id)` e `idempotency_key`; el índice no único de `(object_key, SHA-256)` permite detectar contenido repetido. Así, **cada** `VersionId` de S3 queda en el ledger, pero un hash ya indexado se resuelve como trabajo idempotente sin regenerar embeddings. Todo job referencia obligatoriamente el UUID de su registro de fuente y una clave foránea compuesta verifica que ese UUID corresponde al mismo `object_key` y `s3_version_id` del evento. Solo una versión indexada puede ser actual por objeto. El worker debe reclamar un job mediante transacción/lease antes de mutar el estado. El ETag se guarda como marcador opaco y el SHA-256 sigue siendo la prueba del cambio real.

Los adaptadores de recuperación deben consultar exclusivamente [`rag_cv.active_chunks`](infra/sql/001_initialize_rag_cv.sql), la vista que une chunks con la versión `is_current`. Los chunks vectoriales predecesores permanecen hasta que un sucesor validado sea promovido en la misma transacción; entonces se eliminan sus embeddings para acotar HNSW. Los metadatos de fuente, versión y job siguen auditables en el ledger, y un rollback regenera los embeddings desde la versión correspondiente de S3.

### Verificación de base de datos en QA

Ejecutar únicamente contra una base PostgreSQL con pgvector **controlada y desechable** de QA/CI, usando una identidad con los privilegios de bootstrap:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/001_initialize_rag_cv.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/001_initialize_rag_cv.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/tests/001_initialize_rag_cv_verify.sql
```

El último archivo es una prueba SQL transaccional: verifica objetos, `vector(1024)`, HNSW coseno, FTS, reejecución, eventos duplicados, versiones distintas con el mismo hash, la referencia obligatoria job→fuente, la única versión actual y la exclusión de chunks obsoletos por la vista. Usa un `object_key` derivado de la transacción y termina con `ROLLBACK`, por lo que no conserva sus datos de prueba. También ejecuta una consulta KNN coseno mediante `rag_cv.active_chunks`; es un activo para QA/CI, no una afirmación de ejecución local.

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

## Ciclo de vida operativo

1. Un cambio en `cv.md` llega a S3 (o el scheduler detecta una discrepancia).
2. El caso de uso valida versión, ETag y SHA-256 contra el source ledger.
3. El pipeline idempotente ingiere e indexa solo si hay contenido nuevo.
4. La API consulta PostgreSQL/pgvector, combina resultados con RRF y Strands usa Bedrock para elaborar la respuesta con fuentes.
5. Métricas y alertas permiten detectar fallos, índices degradados y costos anómalos.

## Hoja de ruta

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
