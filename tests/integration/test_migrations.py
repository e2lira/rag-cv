"""RFC-0006 CA-1/CA-2: `alembic upgrade head` crea el esquema completo de 4, y
el ciclo upgrade -> downgrade -> upgrade lo deja identico.

"Identico" se comprueba sobre el contrato entero -- columnas con su tipo,
nulabilidad y valor por defecto, indices, restricciones, disparadores,
funciones, extensiones y la configuracion de texto -- y no sobre los nombres de
las tablas. Comparar solo nombres deja pasar una regresion que pierda
`idx_source_one_current`, el disparador de `tsv` o la clave foranea con
RESTRICT, que es justamente lo que estas pruebas existen para impedir
(auditoria PR #28).
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

_EXPECTED_INDEXES = {
    "idx_cv_chunks_hnsw",
    "idx_cv_chunks_tsv",
    "idx_cv_chunks_tags",
    "idx_cv_chunks_type",
    "idx_cv_chunks_unit_trgm",
    "idx_conversations_key",
    "idx_messages_conv",
    "idx_messages_created",
    "idx_source_object_hash",
    "idx_source_one_current",
    "idx_source_status_observed",
}

_EXPECTED_CONSTRAINTS = {
    "uq_chunk",
    "ck_parts",
    "ck_dates",
    "ck_source_status",
    "ck_source_sha256",
    "ck_source_current",
    "uq_source_object_version",
    "uq_source_id_object_version",
    "ck_job_state",
    "ck_attempt_count",
    "ck_lease",
    "uq_job_idempotency",
    "uq_job_object_version",
    "fk_job_source_version",
}

_EXPECTED_EXTENSIONS = {"vector", "unaccent", "pg_trgm"}

# Contrato de columna, como "tabla | columna | tipo | admite NULL".
#
# Sin esto, `test_roundtrip` da un falso verde: compara la migracion consigo
# misma, asi que degradar CHAR(64) a TEXT deja los dos lados igual de
# degradados y la prueba pasa. Comprobar que los objetos EXISTEN no es
# comprobar que cumplen el contrato -- se eligen las columnas donde el tipo
# es una decision del RFC, no un detalle.
_EXPECTED_COLUMN_CONTRACTS = {
    "cv_chunks | embedding | vector | NO",
    "cv_chunks | tsv | tsvector | NO",
    "cv_chunks | content_hash | bpchar | NO",
    "cv_chunks | tech_tags | _text | NO",
    "cv_chunks | date_end | date | YES",
    "source_documents | content_sha256 | bpchar | NO",
    "source_documents | is_current | bool | NO",
    "source_documents | source_version_id | text | NO",
    "source_documents | source_fingerprint | text | NO",
    "ingestion_jobs | idempotency_key | text | NO",
    "ingestion_jobs | lease_token | uuid | YES",
    "ingestion_jobs | lease_expires_at | timestamptz | YES",
    "ingestion_jobs | attempt_count | int4 | NO",
    "messages | source_chunk_ids | _int8 | NO",
    "rate_buckets | window_start | timestamptz | NO",
}

# RFC-0006 4.1 y A-1: la dimension es Bloqueante y ninguna otra prueba de esta
# suite la lee del esquema -- `check_embedding_dimension` compara contra lo que
# haya, no contra lo que el RFC exige.
_EXPECTED_EMBEDDING_DIM = 1536


def _query(cur: psycopg.Cursor, sql: str) -> set[str]:
    cur.execute(sql)
    return {" | ".join(str(value) for value in row) for row in cur.fetchall()}


def _schema_snapshot(database_url: str) -> dict[str, set[str]]:
    """Huella comparable del contrato del esquema.

    Las funciones se filtran por `pg_depend`: `vector`, `unaccent` y `pg_trgm`
    instalan cientos de funciones en `public`, y solo interesan las nuestras.
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
            "column_contracts": _query(
                cur,
                "SELECT table_name, column_name, udt_name, is_nullable "
                "FROM information_schema.columns WHERE table_schema = 'public'",
            ),
            "indexes": _query(
                cur, "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"
            ),
            "constraints": _query(
                cur,
                "SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE connamespace = 'public'::regnamespace",
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


def _names(entries: set[str]) -> set[str]:
    """Primer campo de cada fila de la huella: el nombre del objeto."""
    return {entry.split(" | ", 1)[0] for entry in entries}


def test_upgrade(database_url: str) -> None:
    snapshot = _schema_snapshot(database_url)

    missing_tables = _EXPECTED_TABLES - snapshot["tables"]
    missing_indexes = _EXPECTED_INDEXES - _names(snapshot["indexes"])
    missing_constraints = _EXPECTED_CONSTRAINTS - _names(snapshot["constraints"])
    missing_extensions = _EXPECTED_EXTENSIONS - snapshot["extensions"]

    assert not missing_tables, f"faltan tablas: {sorted(missing_tables)}"
    assert not missing_indexes, f"faltan indices: {sorted(missing_indexes)}"
    assert not missing_constraints, f"faltan restricciones: {sorted(missing_constraints)}"
    assert not missing_extensions, f"faltan extensiones: {sorted(missing_extensions)}"
    assert "trg_cv_chunks_tsv" in _names(snapshot["triggers"]), "falta el disparador de tsv"
    assert "cv_chunks_tsv_update" in _names(snapshot["functions"]), "falta la funcion del tsv"
    assert "es_unaccent" in snapshot["text_search"], "falta la configuracion es_unaccent"

    violated = _EXPECTED_COLUMN_CONTRACTS - snapshot["column_contracts"]
    assert not violated, f"columnas que no cumplen el contrato de 4: {sorted(violated)}"


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
