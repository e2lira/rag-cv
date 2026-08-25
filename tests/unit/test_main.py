"""RFC-0011 CA-5: python -m app.dev_server arranca y /readyz responde 200 en
Windows. RFC-0021 CA-8: ese /readyz sigue respondiendo una vez que el
arranque validado (RFC-0021) termino, no antes."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.main as main_module
from app.main import app

# Campos que el lifespan pasa al estado de la aplicacion (RFC-0005 6.1 y
# 8). El doble los trae para no acoplar estas pruebas -- que verifican
# RFC-0011 CA-5 y RFC-0021 CA-8 -- a lo que RFC-0005 cablee.
_CLAVES = '{"keys":[{"id":"k1","hash":"' + "0" * 64 + '","role":"read","label":"t","active":true}]}'

pytestmark = pytest.mark.unit


def test_readyz_responds_with_the_contract_shape() -> None:
    """RFC-0011 CA-5, adaptada al contrato real de `/readyz`.

    `/readyz` dejo de ser el marcador de posicion de RFC-0021 y pasa a ser
    el de **RFC-0005 3.1** -- lo dice el propio RFC-0005 11, al mover CA-13
    a RFC-0021: "El `/readyz` con contrato real (3) sigue siendo de este
    RFC". Sin `lifespan` no hay pool, asi que la respuesta honesta es
    `not_ready`; lo que esta prueba conserva de CA-5 es que **la ruta
    existe y responde**. El `200` con todo sano lo cubren la prueba de
    abajo (con `lifespan`) y `test_health.py` contra una base real.
    """
    # TestClient(app) sin "with" no ejecuta el lifespan a proposito: pytest
    # en Windows arranca su propio ProactorEventLoop (no pasa por
    # app/dev_server.py, que es quien fija la politica antes de crear
    # cualquier bucle), asi que ejercitar el lifespan real aqui haria que
    # assert_compatible_loop() rechace el bucle de PYTEST, no el de la
    # aplicacion -- exactamente lo que RFC-0011 #5.1 dice que debe pasar
    # fuera de dev_server.py. Esa comprobacion ya la cubre
    # test_platform.py::test_proactor_detected de forma aislada; aqui solo
    # se prueba la ruta, sin arrancar nada.
    client = TestClient(app)
    response = client.get("/readyz")

    assert response.status_code != 404
    cuerpo = response.json()
    assert cuerpo["status"] in ("ready", "not_ready")
    assert set(cuerpo["checks"]) == {"database", "corpus_indexed", "config"}


def test_readyz_after_successful_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0021 CA-8: con el lifespan real, pero sus dependencias dobladas
    (misma disciplina que test_startup_wiring.py -- no se repite contra una
    base real lo que RFC-0006 ya prueba), /readyz responde 200 solo despues
    de que las cinco comprobaciones se ejecutaron de verdad -- no basta con
    que la ruta responda, tiene que haber pasado por ellas (auditoria de
    PR #44, M-1: la version anterior de este test pasaba igual aunque el
    lifespan no invocara ninguna)."""
    calls: list[str] = []

    class _FakeCursor:
        def execute(self, *args: Any, **kwargs: Any) -> None:
            return None

        def fetchone(self) -> tuple[bool]:
            # Corpus indexado: lo que /readyz consulta para su tercera
            # comprobacion (RFC-0005 3.1).
            return (True,)

        def __enter__(self) -> "_FakeCursor":
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

    class _FakeConn:
        def cursor(self) -> _FakeCursor:
            return _FakeCursor()

    class _FakePool:
        # `timeout` no es opcional por comodidad: /readyz acota la
        # adquisicion para que su 503 llegue antes de que la sonda lo mate.
        def connection(self, timeout: float | None = None) -> Any:
            class _Ctx:
                def __enter__(self) -> _FakeConn:
                    return _FakeConn()

                def __exit__(self, *exc: Any) -> None:
                    return None

            return _Ctx()

        def close(self) -> None:
            pass

    monkeypatch.setattr(main_module, "assert_compatible_loop", lambda: None)
    monkeypatch.setattr(
        main_module,
        "Settings",
        lambda: SimpleNamespace(
            database_url=SecretStr("postgresql://test/test"),
            embedding_dim=1536,
            api_keys_json=_CLAVES,
            rate_limit_per_minute=60,
            rate_limit_per_day=1000,
            corpus_path=Path("corpus/cv.md"),
        ),
        raising=False,
    )
    monkeypatch.setattr(main_module, "build_pool", lambda url: _FakePool(), raising=False)
    monkeypatch.setattr(
        main_module,
        "build_embedder",
        lambda settings, http: SimpleNamespace(model_id="fake@test"),
        raising=False,
    )
    monkeypatch.setattr(main_module, "resolve_expected_head", lambda: "head-x", raising=False)
    # Doblado por la misma razon que en test_startup_wiring: construir el
    # agente de verdad exigiria credenciales del proveedor, y estas pruebas
    # son sobre RFC-0011 CA-5 y RFC-0021 CA-8, no sobre RFC-0004.
    monkeypatch.setattr(
        main_module, "build_agent", lambda settings, persona: object(), raising=False
    )
    monkeypatch.setattr(
        main_module,
        "check_extensions_present",
        lambda conn: calls.append("extensions"),
        raising=False,
    )
    monkeypatch.setattr(
        main_module, "check_pgvector_version", lambda conn: calls.append("pgvector"), raising=False
    )
    monkeypatch.setattr(
        main_module,
        "check_alembic_head",
        lambda conn, expected_head: calls.append("alembic"),
        raising=False,
    )
    monkeypatch.setattr(
        main_module,
        "check_embedding_dimension",
        lambda conn, expected_dim: calls.append("dimension"),
        raising=False,
    )
    monkeypatch.setattr(
        main_module,
        "check_single_embed_model",
        lambda conn, expected_model_id: calls.append("model"),
        raising=False,
    )

    with TestClient(main_module.app) as client:
        response = client.get("/readyz")

    assert response.status_code == 200
    assert calls == ["extensions", "pgvector", "alembic", "dimension", "model"]


def test_startup_aborts_completely_if_a_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0021 7: ninguna comprobacion fallida se degrada a un arranque
    parcial. Si el pool ni siquiera abre, /readyz no debe volverse
    alcanzable -- TestClient(app) como context manager debe fallar al
    entrar, no al pedir la ruta."""

    def _raise_pool(url: str) -> Any:
        raise RuntimeError("la base no acepta conexiones")

    monkeypatch.setattr(main_module, "assert_compatible_loop", lambda: None)
    monkeypatch.setattr(
        main_module,
        "Settings",
        lambda: SimpleNamespace(
            database_url=SecretStr("postgresql://test/test"),
            embedding_dim=1536,
            api_keys_json=_CLAVES,
            rate_limit_per_minute=60,
            rate_limit_per_day=1000,
            corpus_path=Path("corpus/cv.md"),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        main_module,
        "build_embedder",
        lambda settings, http: SimpleNamespace(model_id="fake@test"),
        raising=False,
    )
    monkeypatch.setattr(main_module, "build_pool", _raise_pool, raising=False)

    with pytest.raises(RuntimeError, match="la base no acepta conexiones"):
        with TestClient(main_module.app) as client:
            client.get("/readyz")
