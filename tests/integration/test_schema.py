"""RFC-0006 CA-3 a CA-5, CA-9, CA-10: restricciones e invariantes del esquema
de 4, ejecutados contra una base efimera ya migrada (database_url)."""

import psycopg
import pytest

pytestmark = pytest.mark.integration

_EMBEDDING = "[" + ",".join(["0"] * 1536) + "]"


def _insert_chunk(cur: psycopg.Cursor, *, unit: str = "Backend Python", part: int = 1) -> int:
    cur.execute(
        """
        INSERT INTO cv_chunks
            (section, unit, chunk_type, part, parts, content, content_hash,
             token_count, tech_tags, embedding, embed_model_id)
        VALUES
            (%s, %s, 'experiencia', %s, 1, %s, %s, 10, %s, %s, %s)
        RETURNING id
        """,
        (
            "Experiencia",
            unit,
            part,
            "Desarrollo de servicios en Python",
            "0" * 64,
            ["python", "fastapi"],
            _EMBEDDING,
            "text-embedding-3-small@openai",
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def test_tsv_weights(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        _insert_chunk(cur)
        cur.execute(
            """
            SELECT ts_rank_cd(tsv, websearch_to_tsquery('es_unaccent', %s)) AS rank_unit,
                   ts_rank_cd(tsv, websearch_to_tsquery('es_unaccent', %s)) AS rank_tag,
                   ts_rank_cd(tsv, websearch_to_tsquery('es_unaccent', %s)) AS rank_body
            FROM cv_chunks
            """,
            ("Backend", "fastapi", "servicios"),
        )
        row = cur.fetchone()

    assert row is not None
    rank_unit, rank_tag, rank_body = row
    assert rank_unit > rank_tag > rank_body > 0, (
        f"pesos A/B/C no aplicados en orden: {rank_unit=} {rank_tag=} {rank_body=}"
    )


def test_chunk_type_check(database_url: str) -> None:
    with (
        psycopg.connect(database_url) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            INSERT INTO cv_chunks
                (section, unit, chunk_type, content, content_hash,
                 token_count, embedding, embed_model_id)
            VALUES ('S', 'U', 'no-es-un-tipo-valido', 'c', %s, 1, %s, 'm')
            """,
            ("0" * 64, _EMBEDDING),
        )


def test_unique_upsert(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        _insert_chunk(cur, unit="Backend Python", part=1)
        cur.execute(
            """
            INSERT INTO cv_chunks
                (doc_id, section, unit, chunk_type, part, parts, content, content_hash,
                 token_count, embedding, embed_model_id)
            VALUES ('cv', 'Experiencia', 'Backend Python', 'experiencia', 1, 1,
                    'contenido actualizado', %s, 12, %s, 'm')
            ON CONFLICT (doc_id, unit, part) DO UPDATE SET content = EXCLUDED.content
            """,
            ("1" * 64, _EMBEDDING),
        )
        cur.execute("SELECT count(*), max(content) FROM cv_chunks WHERE unit = 'Backend Python'")
        row = cur.fetchone()

    assert row is not None
    count, content = row
    assert count == 1
    assert content == "contenido actualizado"


def test_cascade(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO conversations (key_id) VALUES ('key-1') RETURNING id",
        )
        row = cur.fetchone()
        assert row is not None
        conversation_id = row[0]
        cur.execute(
            "INSERT INTO messages (conversation_id, role, content) VALUES (%s, 'user', 'hola')",
            (conversation_id,),
        )
        cur.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
        cur.execute("SELECT count(*) FROM messages WHERE conversation_id = %s", (conversation_id,))
        row = cur.fetchone()

    assert row is not None
    assert row[0] == 0


def test_no_fk_on_sources(database_url: str) -> None:
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        chunk_id = _insert_chunk(cur)
        cur.execute(
            "INSERT INTO conversations (key_id) VALUES ('key-2') RETURNING id",
        )
        row = cur.fetchone()
        assert row is not None
        conversation_id = row[0]
        cur.execute(
            """
            INSERT INTO messages (conversation_id, role, content, source_chunk_ids)
            VALUES (%s, 'assistant', 'respuesta', %s)
            """,
            (conversation_id, [chunk_id]),
        )
        # No debe fallar aunque el chunk referenciado ya no exista: no es FK.
        cur.execute("DELETE FROM cv_chunks WHERE id = %s", (chunk_id,))
        cur.execute(
            "SELECT source_chunk_ids FROM messages WHERE conversation_id = %s",
            (conversation_id,),
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == [chunk_id]
