"""RFC-0013 CA-5: los imports de proveedor estan dentro de las ramas.

Alcance verificado, no el literal de RFC-0013 3/12: "un despliegue con
PROVEEDOR=openai_compatible no necesita tener instalados boto3 ni el SDK
de Anthropic" no es alcanzable con strands-agents==1.53.0 -- confirmado
por lectura de .venv/Lib/site-packages/strands/models/__init__.py, que
hace `from .bedrock import BedrockModel` de forma incondicional al
importar el paquete. boto3 es dependencia transitiva de strands.models en
si mismo, no de la rama bedrock de build_model: no hay forma de llegar a
AnthropicModel u OpenAIModel -- por acceso directo o por el __getattr__
perezoso del paquete -- sin que strands.models exista, y ese paquete
exige boto3 para poder importarse.

Lo que SI se sostiene, y es lo que estas pruebas verifican: el SDK de
Anthropic no se importa al ejecutarse la rama openai_compatible, y
viceversa -- ninguna de las dos ramas carga el SDK de la otra.

reload() dentro del bloqueo, no una llamada directa: app.providers.llm ya
esta importado por la coleccion de pytest antes de que el fixture bloquee
nada, y Python cachea modulos -- una llamada directa a build_model()
reusaria el modulo ya cargado sin volver a ejecutar sus imports, y el
test pasaria aunque alguien moviera los imports de proveedor al tope del
archivo. Confirmado por autocomprobacion (ver commit): sin reload(), este
mismo test permanece en verde con los imports al tope."""

import builtins
import importlib
import sys
from collections.abc import Iterator, Mapping, Sequence
from types import ModuleType

import pytest

import app.providers.llm as llm_module
from app.core.settings import Settings

pytestmark = pytest.mark.unit


def _configure(monkeypatch: pytest.MonkeyPatch, proveedor: str, **extra: str) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL_ID", raising=False)
    monkeypatch.setenv("PROVEEDOR", proveedor)
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def _es_del_paquete(nombre: str, paquete: str) -> bool:
    return nombre == paquete or nombre.startswith(f"{paquete}.")


def _blocking_import(*bloqueados: str) -> Iterator[None]:
    """Simula la ausencia de un paquete: cualquier import de ese nombre (o
    de un submodulo suyo) lanza ImportError, cualquier otro import sigue
    su curso normal.

    Purga sys.modules de los nombres bloqueados antes de interceptar
    __import__, y no solo despues: otro test de la misma sesion (p.ej.
    test_llm_factory.py, que usa patch("strands.models.openai...") e
    importa ese modulo real para parchearlo) puede haberlo dejado
    cacheado. Sin la purga, Python devuelve el modulo cacheado sin volver
    a invocar __import__, y el bloqueo nunca se ejecuta de verdad --
    confirmado por autocomprobacion: sin esto, el test queda en verde
    incluso rompiendo el mecanismo real."""
    original = builtins.__import__
    guardados = {
        nombre: modulo
        for nombre, modulo in sys.modules.items()
        if any(_es_del_paquete(nombre, b) for b in bloqueados)
    }
    for nombre in guardados:
        del sys.modules[nombre]

    def fake_import(
        name: str,
        globals: Mapping[str, object] | None = None,
        locals: Mapping[str, object] | None = None,
        fromlist: Sequence[str] | None = (),
        level: int = 0,
    ) -> ModuleType:
        if any(_es_del_paquete(name, b) for b in bloqueados):
            raise ImportError(f"simulado: {name} no disponible")
        return original(name, globals, locals, fromlist, level)

    builtins.__import__ = fake_import
    try:
        yield
    finally:
        builtins.__import__ = original
        sys.modules.update(guardados)


@pytest.fixture
def sin_sdk_openai() -> Iterator[None]:
    # Bloquea el SDK real (openai) y el modulo wrapper de strands
    # (strands.models.openai): si solo el primero, un wrapper ya cacheado
    # en sys.modules por otro test de la sesion (test_llm_factory.py hace
    # patch("strands.models.openai...."), que lo importa para poder
    # parchearlo) nunca vuelve a ejecutar su `import openai` interno, y el
    # bloqueo no se activa de verdad -- confirmado por autocomprobacion.
    yield from _blocking_import("openai", "strands.models.openai")


@pytest.fixture
def sin_sdk_anthropic() -> Iterator[None]:
    yield from _blocking_import("anthropic", "strands.models.anthropic")


@pytest.fixture(autouse=True)
def _restaurar_modulo() -> Iterator[None]:
    """reload() dentro de un test deja el modulo recargado para el resto
    de la sesion -- se recarga una vez mas al final, sin bloqueo, para
    que el siguiente test (en este archivo o cualquier otro) no herede un
    modulo cuyo import fallo a medio camino."""
    yield
    importlib.reload(llm_module)


def test_anthropic_branch_does_not_import_openai_sdk(
    monkeypatch: pytest.MonkeyPatch, sin_sdk_openai: None
) -> None:
    """CA-5: la rama anthropic no carga el SDK de OpenAI -- recargar el
    modulo y construir el proveedor anthropic funciona igual aunque el
    paquete `openai` no este disponible."""
    _configure(monkeypatch, "anthropic", ANTHROPIC_API_KEY="sk-ant-test")

    importlib.reload(llm_module)
    settings = Settings(_env_file=None)
    model = llm_module.build_model(settings)

    assert type(model).__name__ == "AnthropicModel"


def test_openai_compatible_branch_does_not_import_anthropic_sdk(
    monkeypatch: pytest.MonkeyPatch, sin_sdk_anthropic: None
) -> None:
    """CA-5, simetrico: la rama openai_compatible no carga el SDK de
    Anthropic."""
    _configure(
        monkeypatch,
        "openai_compatible",
        OPENAI_COMPATIBLE_API_KEY="sk-deepseek-test",
        OPENAI_COMPATIBLE_BASE_URL="https://api.deepseek.com",
        OPENAI_COMPATIBLE_MODEL_ID="deepseek-chat",
    )

    importlib.reload(llm_module)
    settings = Settings(_env_file=None)
    model = llm_module.build_model(settings)

    assert type(model).__name__ == "OpenAIModel"
