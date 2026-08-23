"""RFC-0006 CA-13/CA-14: invariantes de source_documents (4.5)."""

import psycopg
import pytest

pytestmark = pytest.mark.integration


def _insert_source(
    cur: psycopg.Cursor,
    *,
    object_key: str = "cv.md",
    source_version_id: str,
    is_current: bool,
    ingestion_status: str = "indexed",
) -> None:
    cur.execute(
        """
        INSERT INTO source_documents
            (object_key, source_version_id, source_fingerprint, content_sha256,
             ingestion_status, is_current)
        VALUES (%s, %s, 'fp', %s, %s, %s)
        """,
        (object_key, source_version_id, "0" * 64, ingestion_status, is_current),
    )


def test_one_current_per_object(database_url: str) -> None:
    with (
        psycopg.connect(database_url) as conn,
        pytest.raises(psycopg.errors.UniqueViolation),
        conn.cursor() as cur,
    ):
        _insert_source(cur, source_version_id="v1", is_current=True)
        _insert_source(cur, source_version_id="v2", is_current=True)


def test_current_requires_indexed(database_url: str) -> None:
    with (
        psycopg.connect(database_url) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
        conn.cursor() as cur,
    ):
        _insert_source(cur, source_version_id="v1", is_current=True, ingestion_status="processing")
