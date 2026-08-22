-- Verification for infra/sql/001_initialize_rag_cv.sql
-- Run only after applying the bootstrap twice to a controlled PostgreSQL instance
-- with pgvector installed. Intended invocation:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/tests/001_initialize_rag_cv_verify.sql
-- The test data is rolled back, so it is rerunnable and leaves no records behind.

\set ON_ERROR_STOP on

BEGIN;

SELECT set_config(
    'rag_cv.verify_object_key',
    format('verification/%s/cv.md', txid_current()),
    true
);
SELECT set_config(
    'rag_cv.verify_idempotency_key',
    format('verify-event-%s', txid_current()),
    true
);

DO $$
DECLARE
    embedding_type text;
    hnsw_definition text;
    fts_definition text;
BEGIN
    IF to_regclass('rag_cv.source_documents') IS NULL
       OR to_regclass('rag_cv.ingestion_jobs') IS NULL
       OR to_regclass('rag_cv.rag_chunks') IS NULL
       OR to_regclass('rag_cv.active_chunks') IS NULL THEN
        RAISE EXCEPTION 'Expected rag_cv relations are missing';
    END IF;

    SELECT format_type(attribute.atttypid, attribute.atttypmod)
      INTO embedding_type
      FROM pg_attribute AS attribute
     WHERE attribute.attrelid = 'rag_cv.rag_chunks'::regclass
       AND attribute.attname = 'embedding'
       AND NOT attribute.attisdropped;

    IF embedding_type <> 'vector(1024)' THEN
        RAISE EXCEPTION 'Expected embedding type vector(1024), got %', embedding_type;
    END IF;

    IF to_regconfig('public.es_unaccent') IS NULL
       OR NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'unaccent') THEN
        RAISE EXCEPTION 'Expected public.es_unaccent configuration and unaccent extension';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_attribute AS attribute
        WHERE attribute.attrelid = 'rag_cv.ingestion_jobs'::regclass
          AND attribute.attname = 'source_document_id'
          AND attribute.attnotnull
          AND NOT attribute.attisdropped
    ) THEN
        RAISE EXCEPTION 'ingestion_jobs.source_document_id must be NOT NULL';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'rag_cv.rag_chunks'::regclass
          AND tgname = 'rag_chunks_update_tsv'
          AND NOT tgisinternal
    ) THEN
        RAISE EXCEPTION 'Expected materialized tsv maintenance trigger';
    END IF;

    SELECT pg_get_indexdef(index_class.oid)
      INTO hnsw_definition
      FROM pg_class AS index_class
     WHERE index_class.oid = 'rag_cv.rag_chunks_embedding_hnsw'::regclass;

    IF hnsw_definition NOT ILIKE '%USING hnsw%'
       OR hnsw_definition NOT ILIKE '%vector_cosine_ops%' THEN
        RAISE EXCEPTION 'Expected cosine HNSW index, got %', hnsw_definition;
    END IF;

    SELECT pg_get_indexdef(index_class.oid)
      INTO fts_definition
      FROM pg_class AS index_class
     WHERE index_class.oid = 'rag_cv.rag_chunks_content_fts_idx'::regclass;

    IF fts_definition NOT ILIKE '%USING gin (tsv)%' THEN
        RAISE EXCEPTION 'Expected GIN index on materialized tsv column, got %', fts_definition;
    END IF;
END;
$$;

-- First version: indexed and current, with a chunk that replacement must remove.
INSERT INTO rag_cv.source_documents (
    object_key, s3_version_id, s3_etag, content_sha256, ingestion_status, is_current
) VALUES (
    current_setting('rag_cv.verify_object_key'), 'verify-version-1', 'verify-etag-1', repeat('a', 64), 'indexed', true
);

INSERT INTO rag_cv.rag_chunks (
    source_document_id, ordinal, content, content_sha256, embedding
)
SELECT id, 0, 'old current chunk', repeat('c', 64),
       (ARRAY[1::real] || array_fill(0::real, ARRAY[1023]))::vector
FROM rag_cv.source_documents
WHERE object_key = current_setting('rag_cv.verify_object_key') AND s3_version_id = 'verify-version-1';

-- A new S3 version with the same bytes must remain ledgered; it must not conflict
-- on the hash. The future worker uses the hash lookup to skip re-embedding it.
INSERT INTO rag_cv.source_documents (
    object_key, s3_version_id, s3_etag, content_sha256, ingestion_status
) VALUES (
    current_setting('rag_cv.verify_object_key'), 'verify-version-2', 'verify-etag-2', repeat('a', 64), 'discovered'
);

-- Two identical event deliveries must produce one job ledger entry.
INSERT INTO rag_cv.ingestion_jobs (idempotency_key, object_key, s3_version_id, source_document_id, job_state)
SELECT current_setting('rag_cv.verify_idempotency_key'), current_setting('rag_cv.verify_object_key'),
       'verify-version-2', id, 'pending'
FROM rag_cv.source_documents
WHERE object_key = current_setting('rag_cv.verify_object_key') AND s3_version_id = 'verify-version-2';

INSERT INTO rag_cv.ingestion_jobs (idempotency_key, object_key, s3_version_id, source_document_id, job_state)
SELECT current_setting('rag_cv.verify_idempotency_key'), current_setting('rag_cv.verify_object_key'),
       'verify-version-2', id, 'pending'
FROM rag_cv.source_documents
WHERE object_key = current_setting('rag_cv.verify_object_key') AND s3_version_id = 'verify-version-2'
ON CONFLICT (idempotency_key) DO NOTHING;

INSERT INTO rag_cv.ingestion_jobs (idempotency_key, object_key, s3_version_id, source_document_id, job_state)
SELECT current_setting('rag_cv.verify_idempotency_key') || '-replayed', current_setting('rag_cv.verify_object_key'),
       'verify-version-2', id, 'pending'
FROM rag_cv.source_documents
WHERE object_key = current_setting('rag_cv.verify_object_key') AND s3_version_id = 'verify-version-2'
ON CONFLICT (object_key, s3_version_id) DO NOTHING;

DO $$
BEGIN
    IF (SELECT count(*) FROM rag_cv.source_documents
        WHERE object_key = current_setting('rag_cv.verify_object_key') AND content_sha256 = repeat('a', 64)) <> 2 THEN
        RAISE EXCEPTION 'Same content on distinct S3 versions was not ledgered twice';
    END IF;

    IF (SELECT count(*) FROM rag_cv.ingestion_jobs
        WHERE object_key = current_setting('rag_cv.verify_object_key') AND s3_version_id = 'verify-version-2') <> 1 THEN
        RAISE EXCEPTION 'Duplicate event produced more than one idempotent job';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM rag_cv.ingestion_jobs AS job
        JOIN rag_cv.source_documents AS source ON source.id = job.source_document_id
        WHERE job.object_key = current_setting('rag_cv.verify_object_key')
          AND job.s3_version_id = 'verify-version-2'
          AND source.object_key = job.object_key
          AND source.s3_version_id = job.s3_version_id
    ) THEN
        RAISE EXCEPTION 'Job was not attached to its exact source version';
    END IF;
END;
$$;

-- Replacement is one transaction: stage successor chunks, retire predecessor (the
-- trigger removes its vectors), then promote successor before deferred checks run.
INSERT INTO rag_cv.source_documents (
    object_key, s3_version_id, s3_etag, content_sha256, ingestion_status, is_current
) VALUES (
    current_setting('rag_cv.verify_object_key'), 'verify-version-3', 'verify-etag-3', repeat('b', 64), 'indexed', false
);

INSERT INTO rag_cv.rag_chunks (
    source_document_id, ordinal, content, content_sha256, embedding
)
SELECT id, 0, 'informática current chunk', repeat('d', 64),
       (ARRAY[0::real, 1::real] || array_fill(0::real, ARRAY[1022]))::vector
FROM rag_cv.source_documents
WHERE object_key = current_setting('rag_cv.verify_object_key') AND s3_version_id = 'verify-version-3';

UPDATE rag_cv.source_documents
   SET is_current = false, ingestion_status = 'superseded'
 WHERE object_key = current_setting('rag_cv.verify_object_key') AND s3_version_id = 'verify-version-1';

UPDATE rag_cv.source_documents
   SET is_current = true
 WHERE object_key = current_setting('rag_cv.verify_object_key') AND s3_version_id = 'verify-version-3';

SET CONSTRAINTS ALL IMMEDIATE;

DO $$
DECLARE
    nearest_content text;
    version_one_id uuid;
BEGIN
    IF (SELECT count(*) FROM rag_cv.source_documents
        WHERE object_key = current_setting('rag_cv.verify_object_key') AND is_current) <> 1 THEN
        RAISE EXCEPTION 'Single-current-version contract is not enforced';
    END IF;

    IF EXISTS (
        SELECT 1 FROM rag_cv.active_chunks WHERE content = 'old current chunk'
    ) OR NOT EXISTS (
        SELECT 1 FROM rag_cv.active_chunks WHERE content = 'informática current chunk'
    ) THEN
        RAISE EXCEPTION 'active_chunks did not exclude stale chunks or include current chunks';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM rag_cv.rag_chunks AS chunk
        JOIN rag_cv.source_documents AS source ON source.id = chunk.source_document_id
        WHERE source.object_key = current_setting('rag_cv.verify_object_key')
          AND source.s3_version_id = 'verify-version-1'
    ) THEN
        RAISE EXCEPTION 'Superseded source still retains live vector chunks';
    END IF;

    SELECT content
      INTO nearest_content
      FROM rag_cv.active_chunks
     ORDER BY embedding <=> (ARRAY[0::real, 1::real] || array_fill(0::real, ARRAY[1022]))::vector
     LIMIT 1;

    IF nearest_content <> 'informática current chunk' THEN
        RAISE EXCEPTION 'Cosine nearest-neighbor query returned %, expected only active chunk', nearest_content;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM rag_cv.active_chunks
        WHERE tsv @@ websearch_to_tsquery('es_unaccent', 'informatica')
    ) THEN
        RAISE EXCEPTION 'Unaccent-aware lexical query did not match informática';
    END IF;

    SELECT id INTO version_one_id
      FROM rag_cv.source_documents
     WHERE object_key = current_setting('rag_cv.verify_object_key')
       AND s3_version_id = 'verify-version-1';

    -- A job cannot name a source UUID from another version: the composite FK must
    -- reject it even though that UUID itself exists.
    BEGIN
        INSERT INTO rag_cv.ingestion_jobs (
            idempotency_key, object_key, s3_version_id, source_document_id, job_state
        ) VALUES (
            current_setting('rag_cv.verify_idempotency_key') || '-mismatched-source',
            current_setting('rag_cv.verify_object_key'), 'verify-version-3', version_one_id, 'pending'
        );
        RAISE EXCEPTION 'Composite job/source-version foreign key was not enforced';
    EXCEPTION WHEN foreign_key_violation THEN
        NULL;
    END;
END;
$$;

ROLLBACK;

\echo 'rag_cv bootstrap verification passed'
