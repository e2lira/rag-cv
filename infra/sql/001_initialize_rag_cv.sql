-- rag-cv: bootstrap schema for QA and PROD
--
-- Usage (from a controlled deployment identity):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/001_initialize_rag_cv.sql
--
-- Preconditions
-- * PostgreSQL with the pgvector extension package installed (RDS parameter/version
--   selection must support it), plus the pgcrypto and unaccent extensions available.
-- * The migration identity may CREATE EXTENSION, CREATE SCHEMA, CREATE TABLE,
--   CREATE FUNCTION and CREATE INDEX.  The runtime application role should receive
--   only the minimum DML/USAGE grants after this bootstrap; do not run it as that role.
-- * Run separately against the QA and PROD databases. It is additive/idempotent for
--   a new rag_cv schema and deliberately contains no destructive DROP TABLE, VACUUM
--   or REINDEX command. The guarded legacy unique-constraint removal below preserves
--   all rows and is needed to retain unchanged S3 versions in the ledger.
--
-- Compatibility and operations
-- * This establishes the first schema version. Future changes must be additive and
--   backward-compatible migrations, deployed before application code depends on them.
-- * HNSW maintenance is an operational runbook action: assess bloat/latency first,
--   then run REINDEX INDEX CONCURRENTLY rag_cv.rag_chunks_embedding_hnsw outside a
--   transaction, followed by VACUUM ANALYZE as appropriate. Never do it per upload.
-- * S3 ETags are opaque markers (they are not treated as content hashes); SHA-256 is
--   the authoritative content-change check.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS unaccent;

-- Keep the configuration in public so the documented
-- websearch_to_tsquery('es_unaccent', :query) contract resolves under the
-- standard application search_path. The explicit mapping makes accents and
-- case-insensitive Spanish stemming deterministic across QA and PROD.
DO $$
BEGIN
    IF to_regconfig('public.es_unaccent') IS NULL THEN
        CREATE TEXT SEARCH CONFIGURATION public.es_unaccent (COPY = spanish);
    END IF;
END;
$$;

ALTER TEXT SEARCH CONFIGURATION public.es_unaccent
    ALTER MAPPING FOR hword, hword_part, word WITH unaccent, spanish_stem;

CREATE SCHEMA IF NOT EXISTS rag_cv;

COMMENT ON SCHEMA rag_cv IS
  'RAG-CV application data. Objects are created by migration role; application roles use least-privilege grants.';

CREATE TABLE IF NOT EXISTS rag_cv.source_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    object_key text NOT NULL,
    s3_version_id text NOT NULL,
    s3_etag text NOT NULL,
    content_sha256 char(64) NOT NULL,
    ingestion_status text NOT NULL DEFAULT 'discovered',
    is_current boolean NOT NULL DEFAULT false,
    source_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    observed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    indexed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT source_documents_status_check
        CHECK (ingestion_status IN ('discovered', 'processing', 'indexed', 'failed', 'superseded')),
    CONSTRAINT source_documents_sha256_check
        CHECK (content_sha256 ~ '^[0-9A-Fa-f]{64}$'),
    CONSTRAINT source_documents_current_status_check
        CHECK (NOT is_current OR ingestion_status = 'indexed'),
    CONSTRAINT source_documents_object_version_key UNIQUE (object_key, s3_version_id),
    CONSTRAINT source_documents_id_object_version_key UNIQUE (id, object_key, s3_version_id)
);

COMMENT ON TABLE rag_cv.source_documents IS
  'Source-version ledger. Every observed S3 VersionId is retained, including versions with unchanged content.';
COMMENT ON COLUMN rag_cv.source_documents.s3_etag IS
  'Opaque S3 change marker retained for traceability; it must not be used as a content hash.';
COMMENT ON COLUMN rag_cv.source_documents.is_current IS
  'Exactly zero or one successfully indexed source version is current for a given object key.';

-- Earlier bootstrap drafts made (object_key, content_sha256) unique. Retire that
-- constraint without deleting ledger history: S3 can create a new VersionId whose
-- bytes are unchanged, and that version must remain auditable. Job handling uses
-- idempotency and the existing hash lookup to skip re-embedding unchanged content.
ALTER TABLE rag_cv.source_documents
    DROP CONSTRAINT IF EXISTS source_documents_object_hash_key;

CREATE INDEX IF NOT EXISTS source_documents_object_hash_idx
    ON rag_cv.source_documents (object_key, content_sha256);

CREATE UNIQUE INDEX IF NOT EXISTS source_documents_one_current_object_key
    ON rag_cv.source_documents (object_key)
    WHERE is_current;

CREATE INDEX IF NOT EXISTS source_documents_status_observed_idx
    ON rag_cv.source_documents (ingestion_status, observed_at DESC);

-- The composite candidate key lets a job's source_document_id prove it refers to
-- the same immutable object_key + S3 VersionId carried by the event payload.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'rag_cv.source_documents'::regclass
          AND conname = 'source_documents_id_object_version_key'
    ) THEN
        ALTER TABLE rag_cv.source_documents
            ADD CONSTRAINT source_documents_id_object_version_key
            UNIQUE (id, object_key, s3_version_id);
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS rag_cv.ingestion_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key text NOT NULL,
    object_key text NOT NULL,
    s3_version_id text NOT NULL,
    source_document_id uuid NOT NULL,
    job_state text NOT NULL DEFAULT 'pending',
    attempt_count integer NOT NULL DEFAULT 0,
    lease_token uuid,
    lease_expires_at timestamptz,
    error_code text,
    error_detail text,
    job_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ingestion_jobs_state_check
        CHECK (job_state IN ('pending', 'processing', 'succeeded', 'failed', 'dead_lettered')),
    CONSTRAINT ingestion_jobs_attempt_count_check CHECK (attempt_count >= 0),
    CONSTRAINT ingestion_jobs_lease_check
        CHECK ((lease_token IS NULL) = (lease_expires_at IS NULL)),
    CONSTRAINT ingestion_jobs_idempotency_key_key UNIQUE (idempotency_key),
    CONSTRAINT ingestion_jobs_object_version_key UNIQUE (object_key, s3_version_id),
    CONSTRAINT ingestion_jobs_source_version_fkey
        FOREIGN KEY (source_document_id, object_key, s3_version_id)
        REFERENCES rag_cv.source_documents (id, object_key, s3_version_id)
        ON DELETE RESTRICT
);

COMMENT ON TABLE rag_cv.ingestion_jobs IS
  'Idempotent ingestion work ledger. The unique keys prevent duplicate S3 event processing under concurrent workers.';
COMMENT ON COLUMN rag_cv.ingestion_jobs.source_document_id IS
  'Required immutable source-version record. Composite FK verifies it matches this job object_key and S3 VersionId.';

-- Existing pre-bootstrap jobs cannot be safely guessed. The migration stops rather
-- than silently attaching them to a source; repair any NULL rows before rerunning.
ALTER TABLE rag_cv.ingestion_jobs
    ALTER COLUMN source_document_id SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'rag_cv.ingestion_jobs'::regclass
          AND conname = 'ingestion_jobs_source_version_fkey'
    ) THEN
        ALTER TABLE rag_cv.ingestion_jobs
            ADD CONSTRAINT ingestion_jobs_source_version_fkey
            FOREIGN KEY (source_document_id, object_key, s3_version_id)
            REFERENCES rag_cv.source_documents (id, object_key, s3_version_id)
            ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS ingestion_jobs_claim_idx
    ON rag_cv.ingestion_jobs (job_state, lease_expires_at, created_at)
    WHERE job_state IN ('pending', 'processing', 'failed');

CREATE INDEX IF NOT EXISTS ingestion_jobs_source_document_idx
    ON rag_cv.ingestion_jobs (source_document_id);

CREATE TABLE IF NOT EXISTS rag_cv.rag_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_document_id uuid NOT NULL REFERENCES rag_cv.source_documents(id) ON DELETE RESTRICT,
    ordinal integer NOT NULL,
    content text NOT NULL,
    content_sha256 char(64) NOT NULL,
    embedding vector(1024) NOT NULL,
    tsv tsvector NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT rag_chunks_ordinal_check CHECK (ordinal >= 0),
    CONSTRAINT rag_chunks_content_sha256_check CHECK (content_sha256 ~ '^[0-9A-Fa-f]{64}$'),
    CONSTRAINT rag_chunks_source_ordinal_key UNIQUE (source_document_id, ordinal)
);

COMMENT ON TABLE rag_cv.rag_chunks IS
  'Live retrieval chunks only. Superseded source versions retain their ledger records but not embeddings.';
COMMENT ON COLUMN rag_cv.rag_chunks.embedding IS
  'pgvector 1024-dimensional embedding; application configuration and model output must match this dimension.';
COMMENT ON COLUMN rag_cv.rag_chunks.tsv IS
  'Materialized Spanish full-text vector generated by trigger with the public.es_unaccent configuration.';

ALTER TABLE rag_cv.rag_chunks
    ADD COLUMN IF NOT EXISTS tsv tsvector;

CREATE INDEX IF NOT EXISTS rag_chunks_source_document_idx
    ON rag_cv.rag_chunks (source_document_id, ordinal);

-- Replace the earlier expression index with the materialized-column contract used
-- by websearch_to_tsquery('es_unaccent', ...), ts_rank_cd, and RRF retrieval.
DROP INDEX IF EXISTS rag_cv.rag_chunks_content_fts_idx;
CREATE INDEX rag_chunks_content_fts_idx
    ON rag_cv.rag_chunks USING gin (tsv);

-- HNSW defaults are intentionally explicit: m=16 balances graph connectivity and
-- memory; ef_construction=64 balances build quality and ingest cost. Tune only from
-- measured recall/latency data, and retain the same vector_cosine_ops distance metric
-- in queries (ORDER BY embedding <=> :query_embedding).
CREATE INDEX IF NOT EXISTS rag_chunks_embedding_hnsw
    ON rag_cv.rag_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE OR REPLACE FUNCTION rag_cv.update_chunk_tsv()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.tsv := to_tsvector('public.es_unaccent'::regconfig, NEW.content);
    RETURN NEW;
END;
$$;

-- Populate the materialized field when upgrading an earlier bootstrap, then make
-- the invariant explicit. This is a lexical-index data migration, not HNSW
-- maintenance and does not run VACUUM or REINDEX.
UPDATE rag_cv.rag_chunks
   SET tsv = to_tsvector('public.es_unaccent'::regconfig, content)
 WHERE tsv IS NULL;

ALTER TABLE rag_cv.rag_chunks
    ALTER COLUMN tsv SET NOT NULL;

-- This is the only supported read contract for retrieval adapters. It prevents a
-- predecessor's chunks from participating in search once a successor is current;
-- predecessor rows are intentionally retained for traceability and rollback.
CREATE OR REPLACE VIEW rag_cv.active_chunks AS
SELECT chunk.*
FROM rag_cv.rag_chunks AS chunk
JOIN rag_cv.source_documents AS source
  ON source.id = chunk.source_document_id
WHERE source.is_current
  AND source.ingestion_status = 'indexed';

COMMENT ON VIEW rag_cv.active_chunks IS
  'Retrieval contract: chunks belonging only to the current indexed version of each source object.';

-- Capacity and replacement contract (performed by one Application use case and one
-- database transaction): create and validate the successor source/chunks first;
-- retire the old current source (which removes its vectors); promote the successor;
-- then complete the job. The transaction makes the replacement externally atomic:
-- any failure rolls back both the successor chunks and predecessor retirement.
-- Chunks are deliberately not historical records: the S3/source ledger is the audit
-- trail. This bootstrap does not delete historical rows from earlier deployments.
--
-- The child-to-parent FK on rag_chunks is ON DELETE RESTRICT, so a source ledger
-- record cannot disappear accidentally. It does not prevent the explicit deletion
-- of child chunks below, which is required to bound the live HNSW corpus.
CREATE OR REPLACE FUNCTION rag_cv.delete_retired_source_chunks()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF (OLD.is_current AND NOT NEW.is_current)
       OR (OLD.ingestion_status <> 'superseded' AND NEW.ingestion_status = 'superseded') THEN
        DELETE FROM rag_cv.rag_chunks WHERE source_document_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION rag_cv.require_current_chunk_source()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- A deferred constraint trigger may run after an earlier predecessor chunk was
    -- removed in this transaction. Such a row is no longer live and needs no check.
    IF NOT EXISTS (SELECT 1 FROM rag_cv.rag_chunks WHERE id = NEW.id) THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM rag_cv.source_documents
        WHERE id = NEW.source_document_id
          AND is_current
          AND ingestion_status = 'indexed'
    ) THEN
        RAISE EXCEPTION
            'rag_chunks require a current indexed source version (source_document_id=%)',
            NEW.source_document_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION rag_cv.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'rag_cv.source_documents'::regclass
          AND tgname = 'source_documents_touch_updated_at'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER source_documents_touch_updated_at
            BEFORE UPDATE ON rag_cv.source_documents
            FOR EACH ROW EXECUTE FUNCTION rag_cv.touch_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'rag_cv.ingestion_jobs'::regclass
          AND tgname = 'ingestion_jobs_touch_updated_at'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER ingestion_jobs_touch_updated_at
            BEFORE UPDATE ON rag_cv.ingestion_jobs
            FOR EACH ROW EXECUTE FUNCTION rag_cv.touch_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'rag_cv.rag_chunks'::regclass
          AND tgname = 'rag_chunks_touch_updated_at'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER rag_chunks_touch_updated_at
            BEFORE UPDATE ON rag_cv.rag_chunks
            FOR EACH ROW EXECUTE FUNCTION rag_cv.touch_updated_at();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'rag_cv.rag_chunks'::regclass
          AND tgname = 'rag_chunks_update_tsv'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER rag_chunks_update_tsv
            BEFORE INSERT OR UPDATE OF content ON rag_cv.rag_chunks
            FOR EACH ROW EXECUTE FUNCTION rag_cv.update_chunk_tsv();
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'rag_cv.source_documents'::regclass
          AND tgname = 'source_documents_delete_retired_chunks'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER source_documents_delete_retired_chunks
            AFTER UPDATE OF is_current, ingestion_status ON rag_cv.source_documents
            FOR EACH ROW EXECUTE FUNCTION rag_cv.delete_retired_source_chunks();
    END IF;

END;
$$;

-- The check is deferred so a successor can be embedded and validated before the
-- predecessor is retired, yet a transaction cannot commit live chunks for a source
-- that is not current/indexed. Recreate the trigger to upgrade earlier bootstraps
-- that used an immediate trigger with the same name.
DROP TRIGGER IF EXISTS rag_chunks_require_current_source ON rag_cv.rag_chunks;
CREATE CONSTRAINT TRIGGER rag_chunks_require_current_source
    AFTER INSERT OR UPDATE OF source_document_id ON rag_cv.rag_chunks
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION rag_cv.require_current_chunk_source();

COMMENT ON FUNCTION rag_cv.touch_updated_at() IS
  'Maintains updated_at without requiring each application adapter to implement it.';
COMMENT ON FUNCTION rag_cv.delete_retired_source_chunks() IS
  'Removes vector chunks when a current source is retired; source ledger rows remain auditable.';
COMMENT ON FUNCTION rag_cv.require_current_chunk_source() IS
  'Deferred commit-time check that prevents embeddings being retained for non-current or non-indexed source versions.';
COMMENT ON FUNCTION rag_cv.update_chunk_tsv() IS
  'Maintains materialized es_unaccent tsvector data for PostgreSQL lexical retrieval and RRF.';
