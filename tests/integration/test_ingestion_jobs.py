"""RFC-0006 CA-15 a CA-18: invariantes de ingestion_jobs (4.4) y su FK al
ledger de source_documents (4.5)."""

import psycopg
import pytest

pytestmark = pytest.mark.integration

_OBJECT_KEY = "cv.md"
_SOURCE_VERSION = "v1"


def _insert_source(cur: psycopg.Cursor) -> None:
    cur.execute(
        """
        INSERT INTO source_documents
            (object_key, source_version_id, source_fingerprint, content_sha256,
             ingestion_status, is_current)
        VALUES (%s, %s, 'fp', %s, 'indexed', true)
        """,
        (_OBJECT_KEY, _SOURCE_VERSION, "0" * 64),
    )


def _insert_job(
    cur: psycopg.Cursor,
    *,
    idempotency_key: str,
    job_state: str = "pending",
    lease_token: str | None = None,
    lease_expires_at: str | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO ingestion_jobs
            (idempotency_key, object_key, source_version_id, source_document_id,
             job_state, lease_token, lease_expires_at)
        VALUES (
            %s, %s, %s,
            (SELECT id FROM source_documents WHERE object_key = %s AND source_version_id = %s),
            %s, %s, %s
        )
        """,
        (
            idempotency_key,
            _OBJECT_KEY,
            _SOURCE_VERSION,
            _OBJECT_KEY,
            _SOURCE_VERSION,
            job_state,
            lease_token,
            lease_expires_at,
        ),
    )


def test_idempotency_key_unique(database_url: str) -> None:
    with (
        psycopg.connect(database_url) as conn,
        pytest.raises(psycopg.errors.UniqueViolation),
        conn.cursor() as cur,
    ):
        _insert_source(cur)
        _insert_job(cur, idempotency_key="same-key")
        _insert_job(cur, idempotency_key="same-key")


def test_lease_pair(database_url: str) -> None:
    with (
        psycopg.connect(database_url) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
        conn.cursor() as cur,
    ):
        _insert_source(cur)
        _insert_job(
            cur,
            idempotency_key="k1",
            lease_token="11111111-1111-1111-1111-111111111111",
            lease_expires_at=None,
        )


def test_job_state_check(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        _insert_source(cur)
        _insert_job(cur, idempotency_key="k1", job_state="dead_lettered")
        conn.commit()

    with (
        psycopg.connect(database_url) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
        conn.cursor() as cur,
    ):
        _insert_source(cur)
        _insert_job(cur, idempotency_key="k2", job_state="no-es-un-estado-valido")


def test_source_delete_restricted(database_url: str) -> None:
    with (
        psycopg.connect(database_url) as conn,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
        conn.cursor() as cur,
    ):
        _insert_source(cur)
        _insert_job(cur, idempotency_key="k1")
        conn.commit()
        cur.execute(
            "DELETE FROM source_documents WHERE object_key = %s AND source_version_id = %s",
            (_OBJECT_KEY, _SOURCE_VERSION),
        )
