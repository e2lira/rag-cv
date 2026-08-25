"""RFC-0005 §14 y A-17: ninguna prueba trae una clave de produccion.

> «**Las claves de prueba son claves de prueba.** Ninguna prueba contiene una
> clave con el prefijo de produccion; el CI no tiene credenciales de ningun
> proveedor y no se le anaden (ADR-0012).»

La clausula no admite excepcion, **tampoco para un caso negativo**: ese
prefijo dentro de un `parametrize` que verifica su rechazo sigue siendo ese
prefijo en el arbol, y quien audita no puede distinguir de un vistazo el
fixture del descuido. Esa es toda la razon de que la prohibicion sea
literal.

**Este archivo tampoco se excluye del escaneo, y por eso ningun prefijo
prohibido aparece escrito entero en el.** Un guardian con una excepcion para
si mismo es mas laxo que la regla que vigila: el `grep` del contrato de
auditoria daria resultados mientras la prueba sigue en verde.

Existe como prueba y no como comprobacion manual porque la infraccion que la
motivo **sobrevivio una auditoria entera** (PR #81, veredicto PASS) y solo
aparecio en la siguiente. Una prohibicion que depende de que alguien se
acuerde de correr un `grep` se erosiona sola.

Los patrones se componen en tiempo de ejecucion por esa misma razon.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_TESTS = Path(__file__).resolve().parents[1]

# Prefijos compuestos a proposito (ver el docstring). El de produccion es el
# de RFC-0005 6.1; los demas son los de los proveedores que ADR-0012 mantiene
# fuera del CI.
_PROHIBIDOS = {
    "clave de produccion (RFC-0005 6.1)": "rcv" + "_live_",
    "clave de Anthropic": "sk-" + "ant-api",
    "clave de OpenAI": "sk-" + "proj-",
    "credencial de AWS": "AKIA" + "IOSFODNN",
}


def _archivos_de_prueba() -> list[Path]:
    """Todos, **incluido este**: ver el docstring del modulo."""
    return sorted(_TESTS.rglob("*.py"))


@pytest.mark.parametrize(("motivo", "prefijo"), sorted(_PROHIBIDOS.items()))
def test_no_test_carries_a_production_key(motivo: str, prefijo: str) -> None:
    """RFC-0005 §14: ninguna prueba contiene una clave de produccion.

    Si esta prueba se pone roja, la respuesta **no** es anadir el archivo a
    una lista de exclusiones: es cambiar el literal por uno de prueba
    (`rcv_test_`, o una cadena que no imite ninguna credencial). Un caso
    negativo no necesita el prefijo real para probar que algo se rechaza.
    """
    infractores = [
        f"{p.relative_to(_TESTS.parent)}:{numero}"
        for p in _archivos_de_prueba()
        for numero, linea in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        if prefijo in linea
    ]

    assert not infractores, f"{motivo} -- prefijo {prefijo!r} encontrado en:\n" + "\n".join(
        infractores
    )
