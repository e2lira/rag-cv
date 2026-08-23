# RFC-0006 — Modelo de datos PostgreSQL + pgvector y migraciones

| Campo | Valor |
| :--- | :--- |
| **Estado** | Aprobado |
| **Depende de** | RFC-0001 |
| **Vigencia en la PoC** | `text-embedding-3-small` de OpenAI, `VECTOR(1536)` y `EMBEDDING_DIM=1536` (RFC-0017 §4) |
| **Fecha** | 2026-08-22 |

---

## 1. Contexto y problema

Una sola base de datos sostiene tres cargas distintas: el índice vectorial y léxico del corpus,
el estado conversacional y la contabilidad operativa (cuotas, uso, costo). Mezclarlas sin
criterio produce índices que compiten y migraciones peligrosas. Este RFC fija el esquema, los
índices, las migraciones y las diferencias controladas entre entornos.

## 2. Alcance

**Entra:** extensiones, DDL, índices, restricciones, migraciones Alembic, pooling,
comprobaciones de arranque, retención y respaldo lógico.

**No entra:** infraestructura de la instancia (RFC-0007), consultas de recuperación (RFC-0003).

### 2.1 Contrato de embeddings vigente para la PoC

La PoC usa `EMBEDDER=openai` con `text-embedding-3-small`, a sus **1536 dimensiones
nativas**. Por tanto, el DDL de este RFC declara `VECTOR(1536)`,
`EMBEDDING_DIM=1536` y el identificador persistido es
`text-embedding-3-small@openai`.

Las referencias históricas a Titan, Bedrock y `VECTOR(1024)` describen únicamente el
camino AWS diferido y **no se implementan en la PoC**. RFC-0017 §4 conserva el
procedimiento de recreación del índice cuando se cambie la dimensión; este RFC fija el
estado objetivo que debe entregar el Desarrollador.

## 3. Extensiones requeridas

```sql
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector >= 0.8
CREATE EXTENSION IF NOT EXISTS unaccent;    -- búsqueda léxica insensible a acentos
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- similitud difusa para nombres de empresa
```

En la PoC, QA usa PostgreSQL 16 con pgvector como servicio nativo del VPS; las tres
extensiones forman parte del aprovisionamiento de RFC-0020. En el PostgreSQL nativo de
Windows de DEV, `unaccent` y `pg_trgm` llegan con el instalador, pero **`vector` hay que
compilarlo** si no está disponible (procedimiento en RFC-0011 §4.2). RDS queda diferido
con el camino AWS.

La versión de pgvector se comprueba al arrancar: por debajo de 0.8 el proceso no arranca (los
parámetros de HNSW y el tipo `halfvec` cambian entre versiones).

### 3.1 Creación de la base de datos y configuración regional

La base se crea siempre con **codificación UTF8 y proveedor de configuración regional ICU**,
en DEV y QA de la PoC; el mismo contrato aplica al camino AWS diferido:

```sql
CREATE DATABASE ragcv
  WITH ENCODING 'UTF8' LOCALE_PROVIDER = 'icu' ICU_LOCALE = 'es-MX' TEMPLATE = template0;
```

Esto no es un detalle cosmético. Si la clasificación de caracteres del clúster no reconoce los
acentuados como letras, `to_tsvector` los trocea mal y la rama léxica de RFC-0003 deja de
encontrar términos con tilde **sin emitir ningún error**. El caso concreto que fuerza la
decisión es DEV: en Windows, la configuración regional nativa (`Spanish_Mexico.1252`) no es
compatible con UTF8, y usar `C` clasificaría mal los acentos. ICU da el mismo comportamiento en
Windows y Ubuntu del VPS, que es exactamente lo que se necesita.

La verificación es obligatoria y forma parte de las pruebas (CA-11), no de la documentación:

```sql
SELECT to_tsvector('es_unaccent', 'Informática Ingeniería');
SELECT to_tsvector('es_unaccent','informática') @@ websearch_to_tsquery('es_unaccent','informatica');
```

### 3.2 Configuración de texto en español

```sql
CREATE TEXT SEARCH CONFIGURATION es_unaccent (COPY = spanish);
ALTER TEXT SEARCH CONFIGURATION es_unaccent
  ALTER MAPPING FOR hword, hword_part, word WITH unaccent, spanish_stem;
```

Se usa `es_unaccent` en el trigger y en la consulta. Sin esto, "informática" y "informatica"
son términos distintos, que es exactamente el error que comete un usuario escribiendo rápido.

## 4. Esquema

### 4.1 `cv_chunks` — corpus indexado

```sql
CREATE TABLE cv_chunks (
    id              BIGSERIAL PRIMARY KEY,
    doc_id          TEXT        NOT NULL DEFAULT 'cv',
    section         TEXT        NOT NULL,
    unit            TEXT        NOT NULL,
    chunk_type      TEXT        NOT NULL
        CHECK (chunk_type IN ('perfil','experiencia','proyecto','habilidad','educacion','faq')),
    part            INT         NOT NULL DEFAULT 1,
    parts           INT         NOT NULL DEFAULT 1,
    content         TEXT        NOT NULL,          -- texto enriquecido (RFC-0002 §4.1)
    content_hash    CHAR(64)    NOT NULL,
    token_count     INT         NOT NULL,
    date_start      DATE,
    date_end        DATE,                          -- NULL = actual
    tech_tags       TEXT[]      NOT NULL DEFAULT '{}',
    embedding       VECTOR(1536) NOT NULL,  -- OpenAI text-embedding-3-small (RFC-0017)
    embed_model_id  TEXT        NOT NULL,
    tsv             TSVECTOR    NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_chunk UNIQUE (doc_id, unit, part),
    CONSTRAINT ck_parts CHECK (part >= 1 AND part <= parts),
    CONSTRAINT ck_dates CHECK (date_end IS NULL OR date_start IS NULL OR date_end >= date_start)
);
```

Decisiones y su motivo:

- **`VECTOR(1536)`**: dimensión nativa de `text-embedding-3-small` de OpenAI. No se
  trunca a 768: cambiar desde el histórico `VECTOR(1024)` ya exige recrear la columna y
  el HNSW, por lo que truncar perdería información sin ahorrar una migración. Un cambio
  futuro de dimensión exige recreación y reindexación completa según RFC-0017 §4.
- **`embed_model_id` por fila:** guarda **modelo + camino de servicio**
  (`text-embedding-3-small@openai`) y permite detectar una mezcla de vectores incomparables,
  que degrada la búsqueda sin dar ningún error. El arranque compara el valor distinto de esa
  columna con el `model_id` del embedder activo y falla si hay más de uno o si no coincide.
- **`UNIQUE (doc_id, unit, part)`** es lo que hace posible el `upsert` idempotente de RFC-0002.
- **`tsv` materializado** (no `GENERATED`, porque `to_tsvector` con configuración propia no es
  inmutable en todos los despliegues): se mantiene por trigger.

```sql
CREATE OR REPLACE FUNCTION cv_chunks_tsv_update() RETURNS trigger AS $fn$
BEGIN
    NEW.tsv := setweight(to_tsvector('es_unaccent', coalesce(NEW.unit, '')), 'A')
             || setweight(to_tsvector('es_unaccent', array_to_string(NEW.tech_tags, ' ')), 'B')
             || setweight(to_tsvector('es_unaccent', coalesce(NEW.content, '')), 'C');
    NEW.updated_at := now();
    RETURN NEW;
END
$fn$ LANGUAGE plpgsql;

CREATE TRIGGER trg_cv_chunks_tsv
BEFORE INSERT OR UPDATE ON cv_chunks
FOR EACH ROW EXECUTE FUNCTION cv_chunks_tsv_update();
```

El **peso por campo** (`A` para la unidad, `B` para el stack, `C` para el cuerpo) es lo que
hace que una consulta con el nombre de la empresa o de una tecnología puntúe alto en la rama
léxica aunque el cuerpo del fragmento sea largo.

### 4.2 Índices

```sql
CREATE INDEX idx_cv_chunks_hnsw ON cv_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_cv_chunks_tsv  ON cv_chunks USING gin (tsv);
CREATE INDEX idx_cv_chunks_tags ON cv_chunks USING gin (tech_tags);
CREATE INDEX idx_cv_chunks_type ON cv_chunks (doc_id, chunk_type);
CREATE INDEX idx_cv_chunks_unit_trgm ON cv_chunks USING gin (unit gin_trgm_ops);
```

`m=16, ef_construction=64` son los valores por defecto de pgvector y son correctos para un
corpus de este tamaño; subirlos solo alarga la construcción sin ganar recall medible por debajo
de decenas de miles de vectores. Se documentan explícitamente para que un cambio futuro sea una
decisión, no un descuido.

### 4.3 Conversaciones

```sql
CREATE TABLE conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_id      TEXT        NOT NULL,          -- dueño: API Key que la creó
    locale      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    turns       INT         NOT NULL DEFAULT 0
);
CREATE INDEX idx_conversations_key ON conversations (key_id, last_seen_at DESC);

CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content         TEXT NOT NULL,
    grounded        BOOLEAN,
    source_chunk_ids BIGINT[] NOT NULL DEFAULT '{}',
    model_id        TEXT,
    prompt_version  INT,
    input_tokens    INT,
    output_tokens   INT,
    tool_calls      INT,
    cost_usd        NUMERIC(10,6),
    latency_ms      INT,
    status          TEXT NOT NULL DEFAULT 'ok'
        CHECK (status IN ('ok','failed','cancelled','degraded')),
    request_id      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_conv ON messages (conversation_id, created_at);
CREATE INDEX idx_messages_created ON messages (created_at);
```

`source_chunk_ids` es un array y **no** una clave foránea a `cv_chunks`: una reindexación puede
eliminar un fragmento y no queremos que eso borre en cascada el historial ni bloquee la
reindexación. La trazabilidad es informativa, no referencial, y así se documenta.

### 4.4 Cuotas y trabajos

```sql
CREATE TABLE rate_buckets (
    key_id      TEXT        NOT NULL,
    window_kind TEXT        NOT NULL CHECK (window_kind IN ('minute','day')),
    window_start TIMESTAMPTZ NOT NULL,
    count       INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, window_kind, window_start)
);

CREATE TABLE ingestion_jobs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status      TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed')),
    force       BOOLEAN NOT NULL DEFAULT false,
    report      JSONB,
    error       TEXT,
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

El incremento de cuota es `INSERT ... ON CONFLICT (key_id, window_kind, window_start) DO UPDATE
SET count = rate_buckets.count + 1 RETURNING count`: atómico en una sola ida y vuelta.

## 5. Migraciones

- Las migraciones se ejecutan con `alembic upgrade head`: desde PowerShell en DEV y como paso
  explícito del despliegue nativo en QA. El paso equivalente de PROD pertenece al camino AWS
  diferido.
- **Alembic**, una migración por RFC que toque el esquema, nombrada
  `NNNN_rfc0006_initial_schema.py`.
- Toda migración tiene `downgrade` **probado**: el CI ejecuta `upgrade head` → `downgrade base`
  → `upgrade head` sobre una base efímera.
- Reglas para migraciones sobre tablas con datos:
  1. Nada de `DROP COLUMN` en el mismo despliegue que deja de usarla: primero se deja de leer,
     se despliega, y se elimina en la siguiente versión (*expand & contract*).
  2. Los índices en PROD se crean con `CREATE INDEX CONCURRENTLY`, fuera de transacción.
  3. Un cambio de `EMBEDDING_DIM` **no** es una migración de columna: es una recreación de la
     tabla de fragmentos más una reindexación con `--force`. Está documentado como
     procedimiento en el runbook (RFC-0010), no automatizado.
- Las migraciones se ejecutan como paso explícito del despliegue (RFC-0008), **nunca** en el
  arranque de la aplicación: con más de una réplica, dos procesos migrando a la vez es una
  carrera con daño real.

## 6. Conexiones y pooling

| Entorno | Pool | Motivo |
| :--- | :--- | :--- |
| DEV | `psycopg_pool` 2–5 | Local |
| QA (VPS) | `psycopg_pool` 2–10 | PostgreSQL nativo del sistema en la misma máquina |
| PROD diferido | `psycopg_pool` 5–20 por instancia | Contrato AWS diferido hasta cerrar ADR-0006 |

- `statement_timeout = 5s` a nivel de sesión de la aplicación; `10s` para el trabajo de ingesta.
- `idle_in_transaction_session_timeout = 10s`: una transacción olvidada bloquea `VACUUM`.
- Comprobación de vivacidad del pool cada 30 s; `/readyz` refleja su estado.

## 7. Comprobaciones de arranque (fail fast)

| # | Comprobación | Acción si falla |
| :--- | :--- | :--- |
| 1 | Extensiones `vector`, `unaccent`, `pg_trgm` presentes | No arranca |
| 2 | `pgvector >= 0.8` | No arranca |
| 3 | Dimensión de `cv_chunks.embedding` == `EMBEDDING_DIM` | No arranca |
| 4 | Un único `embed_model_id` en la tabla y coincide con la configuración | No arranca |
| 5 | Versión de Alembic == `head` esperada | No arranca |
| 6 | `count(cv_chunks) > 0` | Arranca, pero `/readyz` en rojo hasta indexar |

## 8. Retención y respaldo

- `messages` y `conversations` con más de **30 días** se eliminan por trabajo programado diario
  (PRD §8). En la PoC lo ejecuta el cron del VPS; EventBridge pertenece al camino AWS diferido.
- `rate_buckets` con ventana anterior a 48 h se purgan en el mismo trabajo.
- PROD: respaldos automáticos de RDS con retención de 7 días + `snapshot` manual antes de cada
  migración que toque tablas con datos.
- QA: `pg_dump` diario a un volumen del VPS, retención de 7 días. QA es reconstruible desde el
  repositorio, así que el respaldo es comodidad, no requisito.
- El corpus **no** se respalda desde la base de datos: la fuente de verdad es `corpus/cv.md` en
  Git, y la tabla es un derivado reconstruible con una reindexación.

## 9. Criterios de aceptación

| # | Criterio | Verificación |
| :--- | :--- | :--- |
| CA-1 | `alembic upgrade head` sobre una base vacía crea todo el esquema de §4 | `tests/integration/test_migrations.py::test_upgrade` |
| CA-2 | El ciclo `upgrade → downgrade → upgrade` deja el esquema idéntico | `test_migrations.py::test_roundtrip` |
| CA-3 | El trigger de `tsv` aplica pesos A/B/C | `test_schema.py::test_tsv_weights` |
| CA-4 | Insertar un `chunk_type` inválido falla | `test_schema.py::test_chunk_type_check` |
| CA-5 | El `upsert` sobre `(doc_id, unit, part)` no duplica filas | `test_schema.py::test_unique_upsert` |
| CA-6 | Arrancar con `EMBEDDING_DIM=1024` contra una columna de 1536 aborta | `test_startup_checks.py::test_dim_mismatch` |
| CA-7 | Arrancar con dos `embed_model_id` distintos en la tabla aborta | `test_startup_checks.py::test_mixed_models` |
| CA-8 | El incremento de cuota es atómico bajo 50 peticiones concurrentes | `test_rate_buckets.py::test_atomic_increment` |
| CA-9 | Borrar una conversación borra sus mensajes (cascada) | `test_schema.py::test_cascade` |
| CA-10 | Eliminar un `cv_chunk` referenciado en `source_chunk_ids` no falla | `test_schema.py::test_no_fk_on_sources` |
| CA-11 | La búsqueda léxica encuentra "informática" buscando "informatica" | `test_schema.py::test_unaccent_config`, ejecutado en Windows y en Linux |
| CA-12 | La base creada por el bootstrap de DEV y la creada por el CI dan el mismo `to_tsvector` | Comparación de la salida de CA-11 en ambos sistemas |

## 10. Riesgos

| Riesgo | Mitigación |
| :--- | :--- |
| Divergencia de versión de Postgres/pgvector entre DEV y QA | PostgreSQL 16 + pgvector en el VPS, comprobación 2 de §7 y CI Linux como autoridad |
| Configuración regional distinta en el PostgreSQL nativo de Windows | Creación con proveedor ICU en los tres entornos + CA-11/CA-12 como gate |
| pgvector compilado a mano en DEV queda desfasado tras actualizar PostgreSQL | Comprobación 1 de §7 aborta el arranque; procedimiento en RFC-0011 §4.2 y en el runbook |
| Migración bloqueante en PROD | `CREATE INDEX CONCURRENTLY` + *expand & contract* + snapshot previo |
| Crecimiento no acotado de `messages` | Trabajo de retención diario + índice por `created_at` |
| `tsv` desincronizado si alguien inserta con `COPY` sin trigger | El trigger es `BEFORE INSERT OR UPDATE`; `COPY` también lo dispara |

## Contrato de auditoría (gate ADU)

| # | Comprobación | Cómo se verifica | Severidad si falla |
| :--- | :--- | :--- | :--- |
| A-1 | La columna vector es `VECTOR(1536)`; no queda ningún `1024` en `app/`, `migrations/` ni `infra/sql/` fuera del camino AWS diferido documentado | `rg -n "1024" app/ migrations/ infra/sql/` | Bloqueante |
| A-2 | Existen los cinco índices de §4.2 con los parámetros indicados | `\d cv_chunks` sobre base migrada | Mayor |
| A-3 | La configuración de texto es `es_unaccent` y se usa en trigger y consulta | CA-11 | Mayor |
| A-3b | La base se crea con proveedor ICU `es-MX` en DEV, QA y el `conftest` de pruebas | Lectura del bootstrap, del aprovisionamiento nativo y del `conftest` | Mayor |
| A-4 | Toda migración tiene `downgrade` funcional | CA-2 | Bloqueante |
| A-5 | La aplicación no ejecuta migraciones al arrancar | Lectura de `main.py` / `lifespan` | Bloqueante |
| A-6 | Las comprobaciones de arranque 1–5 abortan el proceso | CA-6, CA-7 | Bloqueante |
| A-7 | `source_chunk_ids` no es clave foránea | Lectura del DDL | Menor |
| A-8 | El incremento de cuota es atómico (una sola sentencia) | Lectura del SQL + CA-8 | Mayor |
| A-9 | Los `statement_timeout` de §6 están configurados | Lectura de `engine.py` | Menor |
| A-10 | Existe el trabajo de retención de 30 días y está programado en QA y PROD | Revisión de cron/EventBridge | Mayor |
