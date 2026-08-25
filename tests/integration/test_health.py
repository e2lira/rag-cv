"""RFC-0005 3.1, CA-20 y CA-21: vivacidad y preparacion.

Integracion porque `/readyz` comprueba PostgreSQL de verdad: un doble no
probaria justamente lo que el endpoint existe para detectar.

CA-21 es el reverso y se prueba apuntando a una base que no responde: si
`/healthz` abriera una conexion, se caeria con ella, y `systemd` reiniciaria
un proceso que estaba perfectamente vivo.
"""

import time

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.app_factory import create_app
from app.core.engine import build_pool

pytestmark = pytest.mark.integration

_SHA = "a626cf853a2bf653ebdf04be8a1ffe22062a99c0"
_URL_MUERTA = "postgresql://nadie@127.0.0.1:1/no_existe"


def _entorno(monkeypatch: pytest.MonkeyPatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PROVEEDOR", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("COMMIT_SHA", _SHA)


def _cliente(database_url: str, *, pool_url: str | None = None) -> TestClient:
    app = create_app()
    app.state.db_pool = build_pool(pool_url or database_url, min_size=1, max_size=2)
    return TestClient(app, raise_server_exceptions=False)


def test_readyz_reports_commit_and_checks(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-20: `commit_sha` de la release y el detalle por comprobacion."""
    _entorno(monkeypatch, database_url)
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO cv_chunks "
            "(doc_id, section, unit, chunk_type, content, content_hash, "
            " token_count, embedding, embed_model_id) "
            "VALUES ('cv', 'Experiencia', 'Empresa', 'experiencia', 'texto', "
            f" repeat('0', 64), 1, '[{','.join(['0'] * 1536)}]', 'fake@test')"
        )
        conn.commit()

    respuesta = _cliente(database_url).get("/readyz")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "ready"
    assert cuerpo["commit_sha"] == _SHA
    assert cuerpo["checks"] == {"database": "ok", "corpus_indexed": "ok", "config": "ok"}


def test_readyz_is_503_when_the_corpus_is_not_indexed(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-20: sin corpus indexado la API no puede responder nada util, asi
    que no esta lista -- y el cliente ve cual de las tres fallo."""
    _entorno(monkeypatch, database_url)

    respuesta = _cliente(database_url).get("/readyz")

    assert respuesta.status_code == 503
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "not_ready"
    assert cuerpo["checks"]["corpus_indexed"] == "error"
    assert cuerpo["checks"]["database"] == "ok"


def test_readyz_is_503_when_postgres_does_not_respond(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CA-20: base caida => 503 con la comprobacion en rojo, no un 500."""
    _entorno(monkeypatch, database_url)

    respuesta = _cliente(database_url, pool_url=_URL_MUERTA).get("/readyz")

    assert respuesta.status_code == 503
    assert respuesta.json()["checks"]["database"] == "error"


def test_readyz_answers_quickly_when_postgres_is_down(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una sonda de preparacion que tarda 30 s en decir "no estoy listo" es
    inutil: `systemd` y nginx la matan antes, asi que el `503` de CA-20
    nunca llega a leerse. El pool espera 30 s por defecto; la comprobacion
    tiene que acotarlo.

    Se mide el tiempo transcurrido, no se sincroniza con `sleep` (P-7). El
    margen es amplio a proposito -- se compara contra 5 s cuando el fallo
    tarda 30 -- para que no sea una prueba intermitente (P-10).
    """
    _entorno(monkeypatch, database_url)
    cliente = _cliente(database_url, pool_url=_URL_MUERTA)

    inicio = time.monotonic()
    respuesta = cliente.get("/readyz")
    transcurrido = time.monotonic() - inicio

    assert respuesta.status_code == 503
    assert transcurrido < 5.0, f"/readyz tardo {transcurrido:.1f}s en responder"


def test_healthz_survives_db_outage(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """CA-21: `/healthz` sigue en 200 con PostgreSQL caido.

    Es la diferencia con `/readyz`, y no es cosmetica: si `/healthz` tocara
    la base, `systemd` reiniciaria el proceso cada vez que la base tosiera
    -- justo cuando reiniciar no arregla nada."""
    _entorno(monkeypatch, database_url)

    respuesta = _cliente(database_url, pool_url=_URL_MUERTA).get("/healthz")

    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


class _PoolEspia:
    """Pool que delata cualquier intento de uso.

    Un doble y no la base real porque lo que CA-21 exige verificar es una
    **ausencia**: que no se abra conexion. Contra una base viva eso no se
    observa -- la respuesta es identica -- y contra una muerta tampoco,
    porque `build_readiness` se traga la excepcion y `/healthz` seguiria
    devolviendo 200. La unica forma de verlo es preguntarle al pool.
    """

    def __init__(self) -> None:
        self.usado = False

    def connection(self, *args: object, **kwargs: object) -> object:
        self.usado = True
        raise AssertionError("/healthz no debe abrir conexiones (RFC-0005 3.1, CA-21)")


def test_healthz_opens_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """CA-21, la parte que el 200 no prueba: `/healthz` no toca el pool.

    Comprobar solo el 200 con la base caida deja pasar un `/healthz` que
    abre conexion y se come el fallo: responde 200 igual, pero paga la
    espera del pool en cada sondeo de `systemd` y de nginx -- y con ella,
    la latencia que RNF-1 acota.
    """
    _entorno(monkeypatch, _URL_MUERTA)
    app = create_app()
    espia = _PoolEspia()
    app.state.db_pool = espia

    respuesta = TestClient(app, raise_server_exceptions=False).get("/healthz")

    assert respuesta.status_code == 200
    assert espia.usado is False, "/healthz abrio una conexion"


def test_health_endpoints_need_no_api_key(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RFC-0005 3 y A-4: los dos son publicos. Un sondeo de `systemd` o de
    nginx no lleva credencial, y exigirsela los volveria inservibles."""
    _entorno(monkeypatch, database_url)
    cliente = _cliente(database_url)

    assert cliente.get("/healthz").status_code == 200
    assert cliente.get("/readyz").status_code in (200, 503)
