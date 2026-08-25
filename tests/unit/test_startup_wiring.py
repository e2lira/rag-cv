"""RFC-0021 CA-1/CA-2/CA-2b/CA-5/CA-6: el lifespan de app.main invoca las
cinco comprobaciones de arranque de RFC-0006 7, en el orden de RFC-0021 5,
con assert_compatible_loop() como paso 0 -- unica defensa de RFC-0011 CA-4
dentro de este RFC (RFC-0021 3.1). Aborta en la primera que falla sin
ejecutar las siguientes. El model_id que valida CA-5 sale del embedder
realmente construido, no de una constante.

Todas las dependencias del lifespan se doblan: la disciplina de este RFC es
sobre el cableado, no una repeticion de lo que RFC-0006 ya prueba contra una
base real (RFC-0021 9)."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

import app.main as main_module
from app.agent.builder import AgentFactory
from tests.unit.ingestion_fixtures import VALID_CORPUS

pytestmark = pytest.mark.unit


@lru_cache(maxsize=1)
def corpus_de_prueba() -> Path:
    """Un corpus sintetico en disco, **nunca `corpus/cv.md`**.

    `corpus/` esta en `.gitignore` -- el CV real no se versiona (RFC-0016
    3.3) --, asi que apuntar ahi hace que la prueba pase en la maquina de
    quien la escribio y falle en CI, que es el peor de los dos mundos: el
    rojo llega tarde y contra un cambio que no lo causo.
    """
    destino = Path(tempfile.gettempdir()) / "rfc0005_corpus_de_prueba.md"
    destino.write_text(VALID_CORPUS, encoding="utf-8")
    return destino


class FakePool:
    def __init__(self) -> None:
        self.closed = False

    @contextmanager
    def connection(self) -> Iterator[None]:
        yield None

    def close(self) -> None:
        self.closed = True


class _FakeEmbedder:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id


def patch_successful_startup(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    *,
    pool: FakePool,
    embedder_model_id: str = "fake@test",
) -> None:
    monkeypatch.setattr(main_module, "assert_compatible_loop", lambda: calls.append("loop"))
    monkeypatch.setattr(
        main_module,
        "Settings",
        lambda: SimpleNamespace(
            database_url=SecretStr("postgresql://test/test"),
            embedding_dim=1536,
            # Campos que el lifespan pasa al estado de la aplicacion
            # (RFC-0005 6.1 y 8). El doble los trae para no acoplar estas
            # pruebas -- que verifican el ORDEN de las comprobaciones de
            # RFC-0021 5 -- a lo que RFC-0005 cablee.
            api_keys_json='{"keys":[{"id":"k1","hash":"'
            + "0" * 64
            + '","role":"read","label":"t","active":true}]}',
            rate_limit_per_minute=60,
            rate_limit_per_day=1000,
            # Corpus sintetico, nunca el real: de su front-matter sale
            # `{persona}` del prompt de sistema (RFC-0004 4).
            corpus_path=corpus_de_prueba(),
        ),
        raising=False,
    )
    monkeypatch.setattr(main_module, "build_pool", lambda url: pool, raising=False)
    monkeypatch.setattr(
        main_module,
        "build_embedder",
        lambda settings, http: _FakeEmbedder(embedder_model_id),
        raising=False,
    )
    monkeypatch.setattr(main_module, "resolve_expected_head", lambda: "head-x", raising=False)
    # La FABRICA de agentes se dobla (ADR-0017): construirla de verdad
    # exigiria las credenciales del proveedor, y estas pruebas son sobre el
    # ORDEN del arranque (RFC-0021 5), no sobre RFC-0004. Lo que la fabrica
    # deba ser lo verifica tests/unit/test_agent_wiring.py.
    monkeypatch.setattr(
        AgentFactory,
        "from_settings",
        classmethod(lambda cls, settings, persona: object()),
        raising=False,
    )

    def _recorder(name: str) -> Any:
        def _fn(*args: Any, **kwargs: Any) -> None:
            calls.append(name)

        return _fn

    monkeypatch.setattr(
        main_module, "check_extensions_present", _recorder("extensions"), raising=False
    )
    monkeypatch.setattr(main_module, "check_pgvector_version", _recorder("pgvector"), raising=False)
    monkeypatch.setattr(main_module, "check_alembic_head", _recorder("alembic"), raising=False)
    monkeypatch.setattr(
        main_module, "check_embedding_dimension", _recorder("dimension"), raising=False
    )
    monkeypatch.setattr(main_module, "check_single_embed_model", _recorder("model"), raising=False)


@pytest.mark.asyncio
async def test_all_five_checks_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    patch_successful_startup(monkeypatch, calls, pool=FakePool())

    async with main_module.lifespan(main_module.app):
        pass

    assert {"extensions", "pgvector", "alembic", "dimension", "model"} <= set(calls)


@pytest.mark.asyncio
async def test_checks_run_in_the_order_of_rfc_0021_5(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    patch_successful_startup(monkeypatch, calls, pool=FakePool())

    async with main_module.lifespan(main_module.app):
        pass

    order = [c for c in calls if c != "loop"]
    assert order == ["extensions", "pgvector", "alembic", "dimension", "model"]


_CHECK_ORDER = ["extensions", "pgvector", "alembic", "dimension", "model"]
_CHECK_ATTR = {
    "extensions": "check_extensions_present",
    "pgvector": "check_pgvector_version",
    "alembic": "check_alembic_head",
    "dimension": "check_embedding_dimension",
    "model": "check_single_embed_model",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("failing", _CHECK_ORDER)
async def test_each_check_individually_aborts_the_rest(
    failing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RFC-0021 CA-1 / A-1: cada una de las cinco comprobaciones, al fallar
    por si sola, aborta el arranque sin que se ejecute ninguna de las que
    le siguen -- no solo una comprobacion de muestra."""
    calls: list[str] = []
    patch_successful_startup(monkeypatch, calls, pool=FakePool())

    def _fail(*args: Any, **kwargs: Any) -> None:
        calls.append(failing)
        raise RuntimeError(f"{failing} no cumple")

    monkeypatch.setattr(main_module, _CHECK_ATTR[failing], _fail, raising=False)

    with pytest.raises(RuntimeError, match=f"{failing} no cumple"):
        async with main_module.lifespan(main_module.app):
            pass

    index = _CHECK_ORDER.index(failing)
    assert [c for c in calls if c != "loop"] == _CHECK_ORDER[:index] + [failing]


@pytest.mark.asyncio
async def test_loop_check_runs_before_the_pool_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0021 CA-2b / A-2b -- si el bucle de eventos falla, no debe
    abrirse ninguna conexion. Es la unica defensa de RFC-0011 CA-4 dentro
    de este RFC (RFC-0021 3.1): mover este paso despues del pool haria que
    arrancar con el CLI de uvicorn en Windows fallara por la base y no por
    el bucle."""
    calls: list[str] = []
    pool_opened = False

    def _fail_loop() -> None:
        raise RuntimeError("Bucle de eventos incompatible")

    def _build_pool(url: str) -> FakePool:
        nonlocal pool_opened
        pool_opened = True
        return FakePool()

    patch_successful_startup(monkeypatch, calls, pool=FakePool())
    monkeypatch.setattr(main_module, "assert_compatible_loop", _fail_loop)
    monkeypatch.setattr(main_module, "build_pool", _build_pool, raising=False)

    with pytest.raises(RuntimeError, match="Bucle de eventos incompatible"):
        async with main_module.lifespan(main_module.app):
            pass

    assert pool_opened is False
    assert calls == []


@pytest.mark.asyncio
async def test_model_id_comes_from_the_built_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0021 CA-5: cambiar el embedder construido cambia el valor
    comprobado, sin editar el arranque -- no se compone a mano."""
    calls: list[str] = []
    seen_model_id: list[str] = []

    patch_successful_startup(
        monkeypatch, calls, pool=FakePool(), embedder_model_id="distintivo@test"
    )

    def _check_model(conn: Any, expected_model_id: str) -> None:
        seen_model_id.append(expected_model_id)

    monkeypatch.setattr(main_module, "check_single_embed_model", _check_model, raising=False)

    async with main_module.lifespan(main_module.app):
        pass

    assert seen_model_id == ["distintivo@test"]


@pytest.mark.asyncio
async def test_pool_closes_after_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    """RFC-0021 CA-6 / A-8: el lifespan tiene la mitad de despues del yield."""
    calls: list[str] = []
    pool = FakePool()
    patch_successful_startup(monkeypatch, calls, pool=pool)

    async with main_module.lifespan(main_module.app):
        assert pool.closed is False

    assert pool.closed is True
