"""RFC-0006 initial schema

Revision ID: 0001_rfc0006_initial_schema
Revises:
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_rfc0006_initial_schema"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# La extension y la configuracion de texto ya pueden existir si el bootstrap
# de DEV (RFC-0011, app/core/db_bootstrap.py) corrio antes contra esta misma
# base -- el guardado de catalogo evita que "alembic upgrade head" falle la
# segunda vez que se ejecuta contra una base ya aprovisionada (RFC-0006 3/3.2).
_EXTENSIONS_AND_TEXT_SEARCH = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_ts_config AS config
        JOIN pg_namespace AS namespace ON namespace.oid = config.cfgnamespace
        WHERE namespace.nspname = 'public'
          AND config.cfgname = 'es_unaccent'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION public.es_unaccent (COPY = spanish);
    END IF;
END;
$$;

ALTER TEXT SEARCH CONFIGURATION public.es_unaccent
    ALTER MAPPING FOR hword, hword_part, word WITH unaccent, spanish_stem;
"""

_CV_CHUNKS = """
CREATE TABLE cv_chunks (
    id              BIGSERIAL PRIMARY KEY,
    doc_id          TEXT        NOT NULL DEFAULT 'cv',
    section         TEXT        NOT NULL,
    unit            TEXT        NOT NULL,
    chunk_type      TEXT        NOT NULL
        CHECK (chunk_type IN ('perfil','experiencia','proyecto','habilidad','educacion','faq')),
    part            INT         NOT NULL DEFAULT 1,
    parts           INT         NOT NULL DEFAULT 1,
    content         TEXT        NOT NULL,
    content_hash    CHAR(64)    NOT NULL,
    token_count     INT         NOT NULL,
    date_start      DATE,
    date_end        DATE,
    tech_tags       TEXT[]      NOT NULL DEFAULT '{}',
    embedding       VECTOR(1536) NOT NULL,
    embed_model_id  TEXT        NOT NULL,
    tsv             TSVECTOR    NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_chunk UNIQUE (doc_id, unit, part),
    CONSTRAINT ck_parts CHECK (part >= 1 AND part <= parts),
    CONSTRAINT ck_dates CHECK (date_end IS NULL OR date_start IS NULL OR date_end >= date_start)
);

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

CREATE INDEX idx_cv_chunks_hnsw ON cv_chunks
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX idx_cv_chunks_tsv  ON cv_chunks USING gin (tsv);
CREATE INDEX idx_cv_chunks_tags ON cv_chunks USING gin (tech_tags);
CREATE INDEX idx_cv_chunks_type ON cv_chunks (doc_id, chunk_type);
CREATE INDEX idx_cv_chunks_unit_trgm ON cv_chunks USING gin (unit gin_trgm_ops);
"""

_CONVERSATIONS_AND_MESSAGES = """
CREATE TABLE conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_id      TEXT        NOT NULL,
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
"""

_QUOTAS_AND_JOBS = """
CREATE TABLE rate_buckets (
    key_id      TEXT        NOT NULL,
    window_kind TEXT        NOT NULL CHECK (window_kind IN ('minute','day')),
    window_start TIMESTAMPTZ NOT NULL,
    count       INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (key_id, window_kind, window_start)
);

CREATE TABLE ingestion_jobs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key     TEXT        NOT NULL,
    object_key          TEXT        NOT NULL,
    source_version_id   TEXT        NOT NULL,
    source_document_id  UUID        NOT NULL,
    job_state           TEXT        NOT NULL DEFAULT 'pending',
    attempt_count       INT         NOT NULL DEFAULT 0,
    lease_token         UUID,
    lease_expires_at    TIMESTAMPTZ,
    error_code          TEXT,
    error_detail        TEXT,
    job_metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_job_state
        CHECK (job_state IN ('pending','processing','succeeded','failed','dead_lettered')),
    CONSTRAINT ck_attempt_count CHECK (attempt_count >= 0),
    CONSTRAINT ck_lease CHECK ((lease_token IS NULL) = (lease_expires_at IS NULL)),
    CONSTRAINT uq_job_idempotency UNIQUE (idempotency_key),
    CONSTRAINT uq_job_object_version UNIQUE (object_key, source_version_id),
    CONSTRAINT fk_job_source_version
        FOREIGN KEY (source_document_id, object_key, source_version_id)
        REFERENCES source_documents (id, object_key, source_version_id)
        ON DELETE RESTRICT
);
"""

_LEDGER = """
CREATE TABLE source_documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    object_key          TEXT        NOT NULL,
    source_version_id   TEXT        NOT NULL,
    source_fingerprint  TEXT        NOT NULL,
    content_sha256      CHAR(64)    NOT NULL,
    ingestion_status    TEXT        NOT NULL DEFAULT 'discovered',
    is_current          BOOLEAN     NOT NULL DEFAULT false,
    source_metadata     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    indexed_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_source_status
        CHECK (ingestion_status IN ('discovered','processing','indexed','failed','superseded')),
    CONSTRAINT ck_source_sha256 CHECK (content_sha256 ~ '^[0-9A-Fa-f]{64}$'),
    CONSTRAINT ck_source_current CHECK (NOT is_current OR ingestion_status = 'indexed'),
    CONSTRAINT uq_source_object_version UNIQUE (object_key, source_version_id),
    CONSTRAINT uq_source_id_object_version UNIQUE (id, object_key, source_version_id)
);

CREATE INDEX idx_source_object_hash ON source_documents (object_key, content_sha256);
CREATE UNIQUE INDEX idx_source_one_current ON source_documents (object_key) WHERE is_current;
CREATE INDEX idx_source_status_observed ON source_documents (ingestion_status, observed_at DESC);
"""


def upgrade() -> None:
    op.execute(_EXTENSIONS_AND_TEXT_SEARCH)
    op.execute(_CV_CHUNKS)
    op.execute(_CONVERSATIONS_AND_MESSAGES)
    op.execute(_LEDGER)
    op.execute(_QUOTAS_AND_JOBS)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ingestion_jobs")
    op.execute("DROP TABLE IF EXISTS rate_buckets")
    op.execute("DROP TABLE IF EXISTS source_documents")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS conversations")
    op.execute("DROP TABLE IF EXISTS cv_chunks")
    op.execute("DROP FUNCTION IF EXISTS cv_chunks_tsv_update()")
