"""RFC-0011 CA-5: python -m app.dev_server arranca y /readyz responde 200 en
Windows. RFC-0021 CA-8: ese /readyz sigue respondiendo una vez que el
arranque validado (RFC-0021) termino, no antes."""

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.main as main_module
from app.main import app

pytestmark = pytest.mark.unit


def test_readyz_returns_200() -> None:
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
    assert response.status_code == 200


def test_readyz_after_successful_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0021 CA-8: con el lifespan real, pero sus dependencias dobladas
    (misma disciplina que test_startup_wiring.py -- no se repite contra una
    base real lo que RFC-0006 ya prueba), /readyz responde 200 solo despues
    de que las cinco comprobaciones se ejecutaron de verdad -- no basta con
    que la ruta responda, tiene que haber pasado por ellas (auditoria de
    PR #44, M-1: la version anterior de este test pasaba igual aunque el
    lifespan no invocara ninguna)."""
    calls: list[str] = []

    class _FakePool:
        def connection(self) -> Any:
            class _Ctx:
                def __enter__(self) -> None:
                    return None

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
            database_url=SecretStr("postgresql://test/test"), embedding_dim=1536
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
            database_url=SecretStr("postgresql://test/test"), embedding_dim=1536
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
