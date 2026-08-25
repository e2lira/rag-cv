"""RFC-0001 4: el modulo de configuracion es el UNICO que lee el entorno.

La tabla de capas lo declara como prohibicion explicita ("Leerse os.environ
en cualquier otro sitio"), y una prohibicion que nadie comprueba se erosiona
sola: cada lectura suelta parece inofensiva, y juntas hacen que la
configuracion efectiva del proceso deje de estar en un solo sitio. El dia que
un despliegue se comporta distinto de lo que dice su `.env`, no hay donde
mirar.

Se comprueba sobre el arbol de fuentes y no sobre el comportamiento porque lo
que la regla protege es una propiedad estructural: no existe entrada de
programa que la vulnere de forma observable -- solo un `import` de mas.
"""

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_RAIZ = Path(__file__).resolve().parents[2] / "app"
# La unica excepcion, y por definicion: es la capa de configuracion.
_LECTOR_AUTORIZADO = _RAIZ / "core" / "settings.py"
_LECTURAS = {"environ", "getenv"}


def _lecturas_de_entorno(archivo: Path) -> list[str]:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
    encontradas = []
    for nodo in ast.walk(arbol):
        # `os.environ`, `os.getenv`, `os.environ.get` -- todos caen aqui
        # porque el acceso al atributo es el nodo comun a las tres formas.
        if isinstance(nodo, ast.Attribute) and nodo.attr in _LECTURAS:
            if isinstance(nodo.value, ast.Name) and nodo.value.id == "os":
                encontradas.append(f"{archivo}:{nodo.lineno} os.{nodo.attr}")
    return encontradas


def test_only_the_settings_module_reads_the_environment() -> None:
    """RFC-0001 4: `app/core/settings.py` es la unica lectura de entorno.

    Si esta prueba se pone roja, la respuesta no es anadir una excepcion a
    `_LECTOR_AUTORIZADO`: es mover la variable a `Settings`, que es donde el
    RFC dice que vive."""
    infractores = [
        linea
        for archivo in sorted(_RAIZ.rglob("*.py"))
        if archivo != _LECTOR_AUTORIZADO
        for linea in _lecturas_de_entorno(archivo)
    ]

    assert not infractores, "leen el entorno fuera de la capa de configuracion:\n" + "\n".join(
        infractores
    )
