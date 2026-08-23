"""RFC-0006 auditoria A-10 (logica, no el programado en QA/PROD): purga
mensajes/conversaciones con mas de 30 dias y rate_buckets con mas de 48h."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from app.core.retention import purge_expired_records

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
_OLD_CONVERSATION = _NOW - timedelta(days=31)
_RECENT_CONVERSATION = _NOW - timedelta(days=1)
_OLD_BUCKET = _NOW - timedelta(hours=49)
_RECENT_BUCKET = _NOW - timedelta(hours=1)


def _insert_conversation(cur: psycopg.Cursor, *, key_id: str, last_seen_at: datetime) -> str:
    cur.execute(
        "INSERT INTO conversations (key_id, last_seen_at) VALUES (%s, %s) RETURNING id",
        (key_id, last_seen_at),
    )
    row = cur.fetchone()
    assert row is not None
    return str(row[0])


def test_purges_old_conversations_and_messages(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        old_id = _insert_conversation(cur, key_id="old", last_seen_at=_OLD_CONVERSATION)
        recent_id = _insert_conversation(cur, key_id="recent", last_seen_at=_RECENT_CONVERSATION)
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', 'hola')",
            (old_id,),
        )
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', 'hola')",
            (recent_id,),
        )
        conn.commit()

        report = purge_expired_records(conn, now=_NOW)
        conn.commit()

        cur.execute("SELECT id FROM conversations")
        remaining = {str(row[0]) for row in cur.fetchall()}

    assert report["conversations"] == 1
    assert old_id not in remaining
    assert recent_id in remaining


def test_purges_old_rate_buckets(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO rate_buckets (key_id, window_kind, window_start, count) "
            "VALUES ('old', 'minute', %s, 1)",
            (_OLD_BUCKET,),
        )
        cur.execute(
            "INSERT INTO rate_buckets (key_id, window_kind, window_start, count) "
            "VALUES ('recent', 'minute', %s, 1)",
            (_RECENT_BUCKET,),
        )
        conn.commit()

        report = purge_expired_records(conn, now=_NOW)
        conn.commit()

        cur.execute("SELECT key_id FROM rate_buckets")
        remaining = {row[0] for row in cur.fetchall()}

    assert report["rate_buckets"] == 1
    assert remaining == {"recent"}
