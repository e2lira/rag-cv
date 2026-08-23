"""RFC-0019 3 y 7: el ciclo del sondeo contra una base efimera.

`run_once` recibe `conn`, `embedder` y `settings` explicitos, igual que
`index_corpus` de RFC-0002: el contrato de 3 describe el algoritmo, no la
firma, y la inyeccion explicita lo hace verificable sin tocar una base real
ni construir el embedder por fabrica. FakeEmbedder siempre (ADR-0012,
RFC-0014 P-11).

Las salidas tempranas de los pasos 1 a 3 y el latido comparten el esqueleto
de `run_once`: revertirlo enrojece los cinco criterios a la vez, asi que van
en el mismo par (RFC-0014 6.1.1).
"""

from pathlib import Path
from typing import Any

import psycopg
import pytest

import app.ingestion.watcher as watcher_module
from app.core.settings import Settings
from app.ingestion.watcher import (
    OUTCOME_INDEXED,
    OUTCOME_MISSING_CORPUS,
    OUTCOME_NO_CHANGE,
    OUTCOME_UNSTABLE,
    run_once,
)
from app.retrieval.embedder_fake import FakeEmbedder
from tests.unit.ingestion_fixtures import VALID_CORPUS

pytestmark = pytest.mark.integration


def _settings(monkeypatch: pytest.MonkeyPatch, corpus_path: Path, **extra: str) -> Settings:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.setenv("EMBEDDER", "fake")
    monkeypatch.setenv("CORPUS_PATH", str(corpus_path))
    # Sin espera real: P-7 prohibe time.sleep para sincronizar, y una prueba
    # que tarda 5s por ciclo se acaba desactivando.
    monkeypatch.setenv("WATCHER_STABILITY_DELAY_SECONDS", "0")
    for name, value in extra.items():
        monkeypatch.setenv(name, value)
    return Settings(_env_file=None)


def _seed_current_version(conn: psycopg.Connection, object_key: str, fingerprint: str) -> None:
    """Una version ya vigente, como la dejaria un ciclo anterior."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO source_documents (object_key, source_version_id, "
            "source_fingerprint, content_sha256, ingestion_status, is_current) "
            "VALUES (%s, %s, %s, %s, 'indexed', true)",
            (object_key, "01JTESTVERSION0000000000AA", fingerprint, "a" * 64),
        )
    conn.commit()


def _heartbeat(conn: psycopg.Connection, object_key: str) -> Any:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT last_run_at, last_success_at, last_outcome "
            "FROM watcher_heartbeat WHERE object_key = %s",
            (object_key,),
        )
        return cur.fetchone()


@pytest.mark.asyncio
async def test_no_change_short_circuits(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-1: sin cambios, el ciclo termina tras el stat y una consulta -- no
    lee ni hashea el corpus.

    El espia es global sobre Path.read_bytes y Path.read_text: mas fuerte que
    contar llamadas al embebedor, porque un ciclo que leyera el fichero y
    descartara el resultado tambien dejaria el indice intacto.
    """
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(VALID_CORPUS, encoding="utf-8")
    settings = _settings(monkeypatch, corpus_path)
    object_key = str(corpus_path.resolve())

    with psycopg.connect(database_url) as conn:
        stat = corpus_path.stat()
        _seed_current_version(conn, object_key, f"{stat.st_mtime_ns}-{stat.st_size}")

        def _explode(*args: object, **kwargs: object) -> object:
            raise AssertionError("CA-1: el camino sin cambios no puede leer el corpus")

        monkeypatch.setattr(Path, "read_bytes", _explode)
        monkeypatch.setattr(Path, "read_text", _explode)

        report = await run_once(conn, FakeEmbedder(1536), settings)

    assert report.outcome == OUTCOME_NO_CHANGE
    assert report.embed_calls == 0


@pytest.mark.asyncio
async def test_missing_corpus_is_incident(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-9: un corpus ausente NO significa que el CV quedo vacio. El indice
    vigente no se toca y queda incidente registrado.
    """
    corpus_path = tmp_path / "no-existe.md"
    settings = _settings(monkeypatch, corpus_path)
    object_key = str(corpus_path.resolve())

    with psycopg.connect(database_url) as conn:
        _seed_current_version(conn, object_key, "irrelevante")

        report = await run_once(conn, FakeEmbedder(1536), settings)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM source_documents WHERE object_key = %s AND is_current",
                (object_key,),
            )
            still_current = cur.fetchone()

    assert report.outcome == OUTCOME_MISSING_CORPUS
    assert still_current is not None
    assert still_current[0] == 1, "un corpus ausente retiro la version vigente"


@pytest.mark.asyncio
async def test_unstable_file_skipped(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-5: si la huella cambia durante la comprobacion de estabilidad, el
    fichero se esta escribiendo -- se pierde el ciclo, no se indexa a medias.
    """
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(VALID_CORPUS, encoding="utf-8")
    settings = _settings(monkeypatch, corpus_path)
    object_key = str(corpus_path.resolve())

    huellas = iter(["111-100", "222-200", "333-300"])
    monkeypatch.setattr(watcher_module, "fingerprint", lambda _path: next(huellas))

    with psycopg.connect(database_url) as conn:
        report = await run_once(conn, FakeEmbedder(1536), settings)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM source_documents WHERE object_key = %s", (object_key,)
            )
            versions = cur.fetchone()

    assert report.outcome == OUTCOME_UNSTABLE
    assert versions is not None
    assert versions[0] == 0, "se registro una version de un fichero a medio escribir"


@pytest.mark.asyncio
async def test_heartbeat_always_updated(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-10: toda ejecucion deja latido, incluida la que no halla cambios.
    Es la mitad de ADR-0009: un cron que deja de dispararse no produce error.
    """
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(VALID_CORPUS, encoding="utf-8")
    settings = _settings(monkeypatch, corpus_path)
    object_key = str(corpus_path.resolve())

    with psycopg.connect(database_url) as conn:
        stat = corpus_path.stat()
        _seed_current_version(conn, object_key, f"{stat.st_mtime_ns}-{stat.st_size}")

        await run_once(conn, FakeEmbedder(1536), settings)
        row = _heartbeat(conn, object_key)

    assert row is not None, "el ciclo sin cambios no dejo latido"
    assert row[0] is not None
    assert row[2] == OUTCOME_NO_CHANGE


@pytest.mark.asyncio
async def test_heartbeat_success_vs_run(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-18: last_run_at se escribe siempre; last_success_at solo cuando el
    ciclo comprobo de verdad el corpus.

    Un corpus ausente marca la ejecucion pero NO el exito: si marcara exito,
    borrar el CV dejaria la alerta de RFC-0010 en silencio para siempre --
    justo el fallo que 7.1 existe para impedir.
    """
    corpus_path = tmp_path / "no-existe.md"
    settings = _settings(monkeypatch, corpus_path)
    object_key = str(corpus_path.resolve())

    with psycopg.connect(database_url) as conn:
        await run_once(conn, FakeEmbedder(1536), settings)
        row = _heartbeat(conn, object_key)

    assert row is not None
    assert row[0] is not None, "last_run_at no se escribio"
    assert row[1] is None, "un corpus ausente no puede contar como comprobacion con exito"
    assert row[2] == OUTCOME_MISSING_CORPUS


def _corpus_variant(marker: str) -> str:
    """Una variante del corpus que cambia contenido Y longitud, para que la
    huella `mtime_ns-size` difiera sin depender de la resolucion del reloj."""
    return VALID_CORPUS.replace(
        "Redujo el tiempo de ingesta en 40%.",
        f"Redujo el tiempo de ingesta en 40%. {marker}",
    )


def _ledger(conn: psycopg.Connection, object_key: str) -> list[Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_version_id, ingestion_status, is_current, content_sha256 "
            "FROM source_documents WHERE object_key = %s ORDER BY observed_at",
            (object_key,),
        )
        return list(cur.fetchall())


def _chunk_contents(conn: psycopg.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT string_agg(content, '||' ORDER BY unit, part) FROM cv_chunks")
        row = cur.fetchone()
    return str(row[0]) if row and row[0] else ""


@pytest.mark.asyncio
async def test_change_is_indexed_end_to_end(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-2: un cambio de contenido produce version nueva, su trabajo, y un
    indice que refleja el contenido nuevo."""
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(_corpus_variant("PRIMERA"), encoding="utf-8")
    settings = _settings(monkeypatch, corpus_path)
    object_key = str(corpus_path.resolve())

    with psycopg.connect(database_url) as conn:
        first = await run_once(conn, FakeEmbedder(1536), settings)

        corpus_path.write_text(_corpus_variant("SEGUNDA VERSION MAS LARGA"), encoding="utf-8")
        second = await run_once(conn, FakeEmbedder(1536), settings)

        rows = _ledger(conn, object_key)
        contents = _chunk_contents(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingestion_jobs WHERE object_key = %s", (object_key,))
            jobs = cur.fetchone()

    assert first.outcome == OUTCOME_INDEXED
    assert second.outcome == OUTCOME_INDEXED
    assert len(rows) == 2, "un cambio de contenido no registro version nueva"
    assert jobs is not None
    assert jobs[0] == 2, "cada version debe tener su trabajo (paso 6)"
    assert "SEGUNDA VERSION MAS LARGA" in contents
    assert "PRIMERA" not in contents, "el indice conserva contenido de la version anterior"


@pytest.mark.asyncio
async def test_promotion_single_current(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-16: la promocion deja exactamente una version vigente, con
    ingestion_status='indexed', y degrada la anterior a 'superseded'.

    Las dos restricciones del esquema imponen el orden (RFC-0019 6.1):
    ck_source_current exige 'indexed' antes de is_current, e
    idx_source_one_current prohibe dos vigentes a la vez.
    """
    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(_corpus_variant("UNO"), encoding="utf-8")
    settings = _settings(monkeypatch, corpus_path)
    object_key = str(corpus_path.resolve())

    with psycopg.connect(database_url) as conn:
        await run_once(conn, FakeEmbedder(1536), settings)
        corpus_path.write_text(_corpus_variant("DOS CON MAS TEXTO"), encoding="utf-8")
        await run_once(conn, FakeEmbedder(1536), settings)

        rows = _ledger(conn, object_key)

    current = [r for r in rows if r[2]]
    superseded = [r for r in rows if r[1] == "superseded"]

    assert len(current) == 1, f"deberia haber exactamente una vigente, hay {len(current)}"
    assert current[0][1] == "indexed", "la vigente no quedo en 'indexed'"
    assert len(superseded) == 1, "la version anterior no se degrado a 'superseded'"
    assert not superseded[0][2], "una version 'superseded' sigue marcada vigente"


@pytest.mark.asyncio
async def test_revert_reindexes(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-4: volver a un CV anterior SI regenera embeddings y deja el indice
    consultable.

    Es la trampa de RFC-0019 6: saltarse este caso dejaria el indice sin los
    fragmentos de la version promovida, y el sistema responderia "no encuentro
    nada en el CV" con total seguridad.
    """
    corpus_path = tmp_path / "cv.md"
    original = _corpus_variant("ORIGINAL")
    corpus_path.write_text(original, encoding="utf-8")
    settings = _settings(monkeypatch, corpus_path)

    with psycopg.connect(database_url) as conn:
        await run_once(conn, FakeEmbedder(1536), settings)

        corpus_path.write_text(_corpus_variant("INTERMEDIA MUCHO MAS LARGA"), encoding="utf-8")
        await run_once(conn, FakeEmbedder(1536), settings)

        # La reversion: mismo contenido que la primera, mtime nuevo.
        corpus_path.write_text(original, encoding="utf-8")
        reverted = await run_once(conn, FakeEmbedder(1536), settings)

        contents = _chunk_contents(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM cv_chunks")
            chunk_count = cur.fetchone()

    assert reverted.outcome == OUTCOME_INDEXED
    assert reverted.embed_calls > 0, "la reversion no regenero embeddings"
    assert "ORIGINAL" in contents
    assert "INTERMEDIA" not in contents
    assert chunk_count is not None
    assert chunk_count[0] > 0, "la reversion dejo el indice vacio"


@pytest.mark.asyncio
async def test_revert_respects_ledger_uniqueness(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-8: revertir no viola ninguna restriccion de unicidad del ledger.

    Es donde mas facil seria romperlo: la version revertida repite
    content_sha256 con una 'superseded', y `idx_source_object_hash` NO es
    unico justamente para permitirlo -- pero `uq_source_object_version` si lo
    es, y por eso cada deteccion necesita su propio ULID.
    """
    corpus_path = tmp_path / "cv.md"
    original = _corpus_variant("VUELVE")
    corpus_path.write_text(original, encoding="utf-8")
    settings = _settings(monkeypatch, corpus_path)
    object_key = str(corpus_path.resolve())

    with psycopg.connect(database_url) as conn:
        await run_once(conn, FakeEmbedder(1536), settings)
        corpus_path.write_text(_corpus_variant("OTRA COSA DISTINTA Y LARGA"), encoding="utf-8")
        await run_once(conn, FakeEmbedder(1536), settings)
        corpus_path.write_text(original, encoding="utf-8")
        await run_once(conn, FakeEmbedder(1536), settings)

        rows = _ledger(conn, object_key)

    assert len(rows) == 3, "las tres detecciones deben constar en el ledger"
    assert len({r[0] for r in rows}) == 3, "los ULID de version se repitieron"
    assert len([r for r in rows if r[2]]) == 1, "mas de una version vigente tras revertir"

    hashes = [r[3] for r in rows]
    assert hashes[0] == hashes[2], "la reversion deberia repetir el content_sha256 original"
