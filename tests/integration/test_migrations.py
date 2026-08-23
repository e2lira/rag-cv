"""RFC-0006 CA-1/CA-2: `alembic upgrade head` crea el esquema completo de 4, y
el ciclo upgrade -> downgrade -> upgrade lo deja identico.

"Completo" significa: TODAS las columnas de las seis tablas de 4 (tipo,
nulabilidad y DEFAULT literal), TODAS las restricciones con su definicion
completa (incluida la accion ON DELETE de las FK, y la FK sin nombre explicito
de `messages.conversation_id`), los indices, el disparador, su funcion, las
extensiones y `es_unaccent`. Verificar solo que los nombres existan deja pasar
que `messages.source_chunk_ids` pierda su `DEFAULT '{}'` o que
`ON DELETE CASCADE` se convierta en `NO ACTION` sin que ninguna prueba lo note
(auditoria PR #28, tercera ronda).

`test_roundtrip` compara la migracion CONSIGO MISMA: prueba que el ciclo es
reversible, nunca que el estado inicial sea el correcto -- por eso ninguna de
las dos pruebas puede sustituir a la otra.
"""

from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.conftest import _sqlalchemy_url

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]

_EXPECTED_TABLES = {
    "cv_chunks",
    "conversations",
    "messages",
    "rate_buckets",
    "source_documents",
    "ingestion_jobs",
}

# Los 11 indices que declara 4.2, con su `indexdef` completo -- metodo de
# acceso, columnas, clase de operadores y predicado parcial incluidos. Sin
# esto una regresion del metodo HNSW, `vector_cosine_ops`, o del predicado
# `WHERE is_current` de `idx_source_one_current` pasa en verde con solo
# comprobar que el nombre existe (auditoria PR #28, cuarta ronda).
_EXPECTED_INDEX_DEFS = {
    "idx_cv_chunks_hnsw | CREATE INDEX idx_cv_chunks_hnsw ON public.cv_chunks USING hnsw "
    "(embedding vector_cosine_ops) WITH (m='16', ef_construction='64')",
    "idx_cv_chunks_tsv | CREATE INDEX idx_cv_chunks_tsv ON public.cv_chunks USING gin (tsv)",
    "idx_cv_chunks_tags | CREATE INDEX idx_cv_chunks_tags ON public.cv_chunks USING gin "
    "(tech_tags)",
    "idx_cv_chunks_type | CREATE INDEX idx_cv_chunks_type ON public.cv_chunks USING btree "
    "(doc_id, chunk_type)",
    "idx_cv_chunks_unit_trgm | CREATE INDEX idx_cv_chunks_unit_trgm ON public.cv_chunks "
    "USING gin (unit gin_trgm_ops)",
    "idx_conversations_key | CREATE INDEX idx_conversations_key ON public.conversations "
    "USING btree (key_id, last_seen_at DESC)",
    "idx_messages_conv | CREATE INDEX idx_messages_conv ON public.messages USING btree "
    "(conversation_id, created_at)",
    "idx_messages_created | CREATE INDEX idx_messages_created ON public.messages USING "
    "btree (created_at)",
    "idx_source_object_hash | CREATE INDEX idx_source_object_hash ON public.source_documents "
    "USING btree (object_key, content_sha256)",
    "idx_source_one_current | CREATE UNIQUE INDEX idx_source_one_current ON "
    "public.source_documents USING btree (object_key) WHERE is_current",
    "idx_source_status_observed | CREATE INDEX idx_source_status_observed ON "
    "public.source_documents USING btree (ingestion_status, observed_at DESC)",
}

_EXPECTED_EXTENSIONS = {"vector", "unaccent", "pg_trgm"}

_EXPECTED_TRIGGER_DEF = (
    "trg_cv_chunks_tsv | CREATE TRIGGER trg_cv_chunks_tsv BEFORE INSERT OR UPDATE ON "
    "public.cv_chunks FOR EACH ROW EXECUTE FUNCTION cv_chunks_tsv_update()"
)

_EXPECTED_FUNCTION_DEF = (
    "cv_chunks_tsv_update | CREATE OR REPLACE FUNCTION public.cv_chunks_tsv_update()\n"
    " RETURNS trigger\n"
    " LANGUAGE plpgsql\n"
    "AS $function$\n"
    "BEGIN\n"
    "    NEW.tsv := setweight(to_tsvector('es_unaccent', coalesce(NEW.unit, '')), 'A')\n"
    "             || setweight(to_tsvector('es_unaccent', array_to_string(NEW.tech_tags, "
    "' ')), 'B')\n"
    "             || setweight(to_tsvector('es_unaccent', coalesce(NEW.content, '')), 'C');\n"
    "    NEW.updated_at := now();\n"
    "    RETURN NEW;\n"
    "END\n"
    "$function$\n"
)

_EXPECTED_EMBEDDING_DIM = 1536

# Columna completa de cada tabla de 4: "tabla | columna | tipo | NULL? | default".
# Un `-` en el default significa "sin DEFAULT" (columna obligatoria de la
# aplicacion, no un olvido). El texto del default es el que devuelve
# PostgreSQL, no el literal del CREATE TABLE -- por eso `1` sale como texto
# plano pero `'cv'` sale como `'cv'::text` y `now()` no cambia.
_EXPECTED_COLUMNS = {
    "cv_chunks | id | int8 | NO | nextval('cv_chunks_id_seq'::regclass)",
    "cv_chunks | doc_id | text | NO | 'cv'::text",
    "cv_chunks | section | text | NO | -",
    "cv_chunks | unit | text | NO | -",
    "cv_chunks | chunk_type | text | NO | -",
    "cv_chunks | part | int4 | NO | 1",
    "cv_chunks | parts | int4 | NO | 1",
    "cv_chunks | content | text | NO | -",
    "cv_chunks | content_hash | bpchar | NO | -",
    "cv_chunks | token_count | int4 | NO | -",
    "cv_chunks | date_start | date | YES | -",
    "cv_chunks | date_end | date | YES | -",
    "cv_chunks | tech_tags | _text | NO | '{}'::text[]",
    "cv_chunks | embedding | vector | NO | -",
    "cv_chunks | embed_model_id | text | NO | -",
    "cv_chunks | tsv | tsvector | NO | -",
    "cv_chunks | created_at | timestamptz | NO | now()",
    "cv_chunks | updated_at | timestamptz | NO | now()",
    "conversations | id | uuid | NO | gen_random_uuid()",
    "conversations | key_id | text | NO | -",
    "conversations | locale | text | YES | -",
    "conversations | created_at | timestamptz | NO | now()",
    "conversations | last_seen_at | timestamptz | NO | now()",
    "conversations | turns | int4 | NO | 0",
    "messages | id | uuid | NO | gen_random_uuid()",
    "messages | conversation_id | uuid | NO | -",
    "messages | role | text | NO | -",
    "messages | content | text | NO | -",
    "messages | grounded | bool | YES | -",
    "messages | source_chunk_ids | _int8 | NO | '{}'::bigint[]",
    "messages | model_id | text | YES | -",
    "messages | prompt_version | int4 | YES | -",
    "messages | input_tokens | int4 | YES | -",
    "messages | output_tokens | int4 | YES | -",
    "messages | tool_calls | int4 | YES | -",
    "messages | cost_usd | numeric | YES | -",
    "messages | latency_ms | int4 | YES | -",
    "messages | status | text | NO | 'ok'::text",
    "messages | request_id | text | YES | -",
    "messages | created_at | timestamptz | NO | now()",
    "rate_buckets | key_id | text | NO | -",
    "rate_buckets | window_kind | text | NO | -",
    "rate_buckets | window_start | timestamptz | NO | -",
    "rate_buckets | count | int4 | NO | 0",
    "source_documents | id | uuid | NO | gen_random_uuid()",
    "source_documents | object_key | text | NO | -",
    "source_documents | source_version_id | text | NO | -",
    "source_documents | source_fingerprint | text | NO | -",
    "source_documents | content_sha256 | bpchar | NO | -",
    "source_documents | ingestion_status | text | NO | 'discovered'::text",
    "source_documents | is_current | bool | NO | false",
    "source_documents | source_metadata | jsonb | NO | '{}'::jsonb",
    "source_documents | observed_at | timestamptz | NO | now()",
    "source_documents | indexed_at | timestamptz | YES | -",
    "source_documents | created_at | timestamptz | NO | now()",
    "source_documents | updated_at | timestamptz | NO | now()",
    "ingestion_jobs | id | uuid | NO | gen_random_uuid()",
    "ingestion_jobs | idempotency_key | text | NO | -",
    "ingestion_jobs | object_key | text | NO | -",
    "ingestion_jobs | source_version_id | text | NO | -",
    "ingestion_jobs | source_document_id | uuid | NO | -",
    "ingestion_jobs | job_state | text | NO | 'pending'::text",
    "ingestion_jobs | attempt_count | int4 | NO | 0",
    "ingestion_jobs | lease_token | uuid | YES | -",
    "ingestion_jobs | lease_expires_at | timestamptz | YES | -",
    "ingestion_jobs | error_code | text | YES | -",
    "ingestion_jobs | error_detail | text | YES | -",
    "ingestion_jobs | job_metadata | jsonb | NO | '{}'::jsonb",
    "ingestion_jobs | started_at | timestamptz | YES | -",
    "ingestion_jobs | completed_at | timestamptz | YES | -",
    "ingestion_jobs | created_at | timestamptz | NO | now()",
    "ingestion_jobs | updated_at | timestamptz | NO | now()",
}

# Toda restriccion con contype p/f/u/c (primary key, foreign key, unique,
# check), con su definicion completa via pg_get_constraintdef -- incluida
# `messages_conversation_id_fkey`, que no tiene CONSTRAINT con nombre propio
# en el DDL y por eso quedaba fuera de la version anterior de esta prueba.
# Se excluyen las restricciones NOT NULL que PostgreSQL cataloga aparte
# (contype 'n'): son redundantes con la columna `is_nullable` de arriba y
# distinto motor segun version de PostgreSQL las expone distinto.
_EXPECTED_CONSTRAINT_DEFS = {
    "cv_chunks_pkey | p | PRIMARY KEY (id)",
    "uq_chunk | u | UNIQUE (doc_id, unit, part)",
    "ck_parts | c | CHECK (((part >= 1) AND (part <= parts)))",
    "ck_dates | c | CHECK (((date_end IS NULL) OR (date_start IS NULL) OR "
    "(date_end >= date_start)))",
    "cv_chunks_chunk_type_check | c | CHECK ((chunk_type = ANY (ARRAY["
    "'perfil'::text, 'experiencia'::text, 'proyecto'::text, 'habilidad'::text, "
    "'educacion'::text, 'faq'::text])))",
    "conversations_pkey | p | PRIMARY KEY (id)",
    "messages_pkey | p | PRIMARY KEY (id)",
    "messages_conversation_id_fkey | f | FOREIGN KEY (conversation_id) "
    "REFERENCES conversations(id) ON DELETE CASCADE",
    "messages_role_check | c | CHECK ((role = ANY (ARRAY['user'::text, 'assistant'::text])))",
    "messages_status_check | c | CHECK ((status = ANY (ARRAY["
    "'ok'::text, 'failed'::text, 'cancelled'::text, 'degraded'::text])))",
    "rate_buckets_pkey | p | PRIMARY KEY (key_id, window_kind, window_start)",
    "rate_buckets_window_kind_check | c | CHECK ((window_kind = ANY "
    "(ARRAY['minute'::text, 'day'::text])))",
    "source_documents_pkey | p | PRIMARY KEY (id)",
    "ck_source_status | c | CHECK ((ingestion_status = ANY (ARRAY["
    "'discovered'::text, 'processing'::text, 'indexed'::text, 'failed'::text, "
    "'superseded'::text])))",
    "ck_source_sha256 | c | CHECK ((content_sha256 ~ '^[0-9A-Fa-f]{64}$'::text))",
    "ck_source_current | c | CHECK (((NOT is_current) OR (ingestion_status = 'indexed'::text)))",
    "uq_source_object_version | u | UNIQUE (object_key, source_version_id)",
    "uq_source_id_object_version | u | UNIQUE (id, object_key, source_version_id)",
    "ingestion_jobs_pkey | p | PRIMARY KEY (id)",
    "ck_job_state | c | CHECK ((job_state = ANY (ARRAY["
    "'pending'::text, 'processing'::text, 'succeeded'::text, 'failed'::text, "
    "'dead_lettered'::text])))",
    "ck_attempt_count | c | CHECK ((attempt_count >= 0))",
    "ck_lease | c | CHECK (((lease_token IS NULL) = (lease_expires_at IS NULL)))",
    "uq_job_idempotency | u | UNIQUE (idempotency_key)",
    "uq_job_object_version | u | UNIQUE (object_key, source_version_id)",
    "fk_job_source_version | f | FOREIGN KEY (source_document_id, object_key, "
    "source_version_id) REFERENCES source_documents(id, object_key, "
    "source_version_id) ON DELETE RESTRICT",
}


def _query(cur: psycopg.Cursor, sql: str) -> set[str]:
    cur.execute(sql)
    return {" | ".join(str(value) for value in row) for row in cur.fetchall()}


def _schema_snapshot(database_url: str) -> dict[str, set[str]]:
    """Huella comparable del contrato del esquema.

    Las funciones se filtran por `pg_depend`: `vector`, `unaccent` y `pg_trgm`
    instalan cientos de funciones en `public`, y solo interesan las nuestras.
    Las restricciones se filtran a p/f/u/c: las de tipo 'n' (NOT NULL como
    fila de catalogo) son version-dependientes y redundantes con `columns`.
    """
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        return {
            "tables": _query(
                cur,
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
            ),
            "columns": _query(
                cur,
                "SELECT table_name, column_name, udt_name, is_nullable, "
                "coalesce(column_default, '-') "
                "FROM information_schema.columns WHERE table_schema = 'public'",
            ),
            "indexes": _query(
                cur, "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"
            ),
            "constraints": _query(
                cur,
                "SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE connamespace = 'public'::regnamespace AND contype IN ('p','f','u','c')",
            ),
            "triggers": _query(
                cur,
                "SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger WHERE NOT tgisinternal",
            ),
            "functions": _query(
                cur,
                "SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'public' AND NOT EXISTS ("
                "  SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')",
            ),
            "extensions": _query(cur, "SELECT extname FROM pg_extension"),
            "text_search": _query(
                cur,
                "SELECT c.cfgname FROM pg_ts_config c "
                "JOIN pg_namespace n ON n.oid = c.cfgnamespace "
                "WHERE n.nspname = 'public'",
            ),
        }


def test_upgrade(database_url: str) -> None:
    snapshot = _schema_snapshot(database_url)

    missing_tables = _EXPECTED_TABLES - snapshot["tables"]
    missing_extensions = _EXPECTED_EXTENSIONS - snapshot["extensions"]
    violated_columns = _EXPECTED_COLUMNS - snapshot["columns"]
    violated_constraints = _EXPECTED_CONSTRAINT_DEFS - snapshot["constraints"]
    violated_indexes = _EXPECTED_INDEX_DEFS - snapshot["indexes"]

    assert not missing_tables, f"faltan tablas: {sorted(missing_tables)}"
    assert not missing_extensions, f"faltan extensiones: {sorted(missing_extensions)}"
    assert not violated_columns, (
        f"columnas que no cumplen el contrato de 4: {sorted(violated_columns)}"
    )
    assert not violated_constraints, (
        f"restricciones que no cumplen el contrato de 4: {sorted(violated_constraints)}"
    )
    assert not violated_indexes, (
        f"indices que no cumplen el contrato de 4.2: {sorted(violated_indexes)}"
    )
    assert _EXPECTED_TRIGGER_DEF in snapshot["triggers"], (
        "el disparador de tsv no coincide con el contrato de 4.1"
    )
    assert _EXPECTED_FUNCTION_DEF in snapshot["functions"], (
        "la funcion de tsv no coincide con el contrato de 4.1"
    )
    assert "es_unaccent" in snapshot["text_search"], "falta la configuracion es_unaccent"


def test_embedding_dimension(database_url: str) -> None:
    """RFC-0006 A-1: la columna vector declara 1536. pgvector guarda la
    dimension en `atttypmod` sin desplazamiento."""
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'cv_chunks'::regclass AND attname = 'embedding'"
        )
        row = cur.fetchone()

    assert row is not None, "no existe cv_chunks.embedding"
    assert row[0] == _EXPECTED_EMBEDDING_DIM, (
        f"la migracion declara VECTOR({row[0]}), el RFC exige {_EXPECTED_EMBEDDING_DIM}"
    )


def test_roundtrip(database_url: str) -> None:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _sqlalchemy_url(database_url))

    before = _schema_snapshot(database_url)

    command.downgrade(cfg, "base")
    after_downgrade = _schema_snapshot(database_url)

    command.upgrade(cfg, "head")
    after = _schema_snapshot(database_url)

    assert _EXPECTED_TABLES.isdisjoint(after_downgrade["tables"]), (
        f"downgrade no elimino: {sorted(_EXPECTED_TABLES & after_downgrade['tables'])}"
    )

    for aspect in sorted(before):
        assert after[aspect] == before[aspect], (
            f"el ciclo upgrade/downgrade/upgrade cambio '{aspect}'. "
            f"Perdido: {sorted(before[aspect] - after[aspect])}. "
            f"Añadido: {sorted(after[aspect] - before[aspect])}"
        )
