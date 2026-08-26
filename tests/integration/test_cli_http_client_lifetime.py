"""RFC-0019 7 y RFC-0002 8: el cliente HTTP sigue vivo cuando se embebe.

Las dos CLI construyen el embebedor dentro de `async with httpx2.AsyncClient()`
y despues lo usan. Si el trabajo queda FUERA de ese bloque, el cliente se
cierra al salir y el embebedor arrastra un cliente muerto. En el VPS:

    outcome=failed version=01M0WQWJZBA7B04GQ9AMXS29E5 embed_calls=0
    error_detail: "Cannot send a request, as the client has been closed."

`embed_calls=0` es la firma del defecto: no fallo la llamada al proveedor,
fallo **antes** de poder hacerla.

Aparecio en el despliegue, no en la suite, y conviene entender por que. No fue
que nadie ejecutara la CLI: `test_watcher_cli.py` y `test_indexer_cli.py` ya
invocaban `_run_cli` de punta a punta con `Settings`, `build_pool` y
`build_embedder` reales. El camino estaba cubierto.

Lo que no estaba cubierto era el **recurso**. Las dos fijan `EMBEDDER=fake`, y
`FakeEmbedder` no recibe el cliente HTTP ni lo usa -- deriva el vector de un
sha256 (`app/retrieval/embedder_fake.py`). El unico colaborador capaz de
delatar el defecto era justamente el que la prueba sustituia para no tocar la
red. `OpenAIEmbedder` guarda ese cliente y muere si esta cerrado
(`app/retrieval/embedder_openai.py`).

De ahi la forma de estas pruebas. NO comprueban que la CLI termine bien: eso
ya se comprueba en los dos ficheros citados, y seguia verde con el defecto
presente en produccion. Comprueban lo que el colaborador **recibe** en el
momento de usarlo, que es lo que RFC-0014 7.1 exige cuando el criterio habla
de una continuidad y no de una respuesta (P-13).

No hace falta red ni credenciales del proveedor (ADR-0012): el espia observa
el mismo objeto `AsyncClient` que recibiria `OpenAIEmbedder`, en el mismo
instante, y delega el calculo en `FakeEmbedder`.
"""

from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

import httpx2
import pytest

from app.core.settings import Settings
from app.retrieval.embedder_fake import FakeEmbedder
from tests.unit.ingestion_fixtures import VALID_CORPUS

pytestmark = pytest.mark.integration


class _EmbebedorQueMiraElCliente:
    """Delega en `FakeEmbedder` y anota el estado del cliente al usarse.

    Sustituye a `build_embedder` con su misma firma, asi que recibe el mismo
    `AsyncClient` que recibiria el embebedor real. La asercion no es sobre
    este objeto sino sobre lo que la CLI le entrega (RFC-0014 7.1, P-13).
    """

    def __init__(self, http: httpx2.AsyncClient, dimension: int) -> None:
        self._http = http
        self._delegado = FakeEmbedder(dimension)
        # None mientras nadie haya embebido: distingue "el cliente estaba
        # abierto" de "nunca se llego a embeber", que son fallos distintos.
        self.cerrado_al_embeber: bool | None = None

    @property
    def model_id(self) -> str:
        return self._delegado.model_id

    @property
    def dimension(self) -> int:
        return self._delegado.dimension

    def _anotar(self) -> None:
        self.cerrado_al_embeber = self._http.is_closed

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self._anotar()
        return await self._delegado.embed_documents(texts)

    async def embed_query(self, text: str) -> list[float]:
        self._anotar()
        return await self._delegado.embed_query(text)


def _espiar_el_embebedor(
    monkeypatch: pytest.MonkeyPatch, modulo: ModuleType
) -> list[_EmbebedorQueMiraElCliente]:
    """Reemplaza `build_embedder` en el modulo de la CLI y recoge los espias."""
    espias: list[_EmbebedorQueMiraElCliente] = []

    def _fabricar(settings: Settings, http: httpx2.AsyncClient) -> _EmbebedorQueMiraElCliente:
        espia = _EmbebedorQueMiraElCliente(http, settings.embedding_dim)
        espias.append(espia)
        return espia

    monkeypatch.setattr(modulo, "build_embedder", _fabricar)
    return espias


def _entorno(monkeypatch: pytest.MonkeyPatch, database_url: str, corpus_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("CORPUS_PATH", str(corpus_path))
    monkeypatch.setenv("WATCHER_STABILITY_DELAY_SECONDS", "0")


def _exigir_cliente_vivo(espias: list[_EmbebedorQueMiraElCliente]) -> None:
    assert espias, "la CLI no llego a construir el embebedor"
    estado = espias[0].cerrado_al_embeber
    assert estado is not None, "la CLI no llego a embeber: la prueba no verifico nada"
    assert estado is False, (
        "el cliente HTTP ya estaba cerrado cuando se embebio. El trabajo quedo "
        "fuera del bloque `async with httpx2.AsyncClient()`, que lo cierra al "
        "salir. Con el embebedor real esto es "
        "'Cannot send a request, as the client has been closed.' y embed_calls=0"
    )


@pytest.mark.asyncio
async def test_the_watcher_cli_embeds_with_a_live_http_client(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RFC-0019 7: el ciclo que dispara el cron llega a embeber de verdad."""
    from app.ingestion import watcher

    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(VALID_CORPUS, encoding="utf-8")
    _entorno(monkeypatch, database_url, corpus_path)
    espias = _espiar_el_embebedor(monkeypatch, watcher)

    await watcher._run_cli([])

    _exigir_cliente_vivo(espias)


@pytest.mark.asyncio
async def test_the_indexer_cli_embeds_with_a_live_http_client(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RFC-0002 8: la indexacion manual tiene el mismo bloque, y el mismo fallo.

    Se prueba aparte y no por parametrizacion: son dos entradas distintas de
    dos RFC distintos, y que hoy compartan la forma del defecto no las une.
    """
    from app.ingestion import indexer

    corpus_path = tmp_path / "cv.md"
    corpus_path.write_text(VALID_CORPUS, encoding="utf-8")
    _entorno(monkeypatch, database_url, corpus_path)
    espias = _espiar_el_embebedor(monkeypatch, indexer)

    await indexer._run_cli(["--corpus", str(corpus_path)])

    _exigir_cliente_vivo(espias)
