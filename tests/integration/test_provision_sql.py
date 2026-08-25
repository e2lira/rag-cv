"""RFC-0020 §4, CA-16: el SQL que lleva el aprovisionamiento es ejecutable.

La comprobación del ICU es el único paso irreversible del despliegue —la
configuración regional se fija al crear la base—, y la escribí con un error
que **no se ve leyendo**: `datlocprovider` es de tipo `"char"`, así que
`datlocprovider || ' ' || datcollate` deja a PostgreSQL sin saber qué
operador usar y falla con *«operator is not unique»*.

El síntoma llegó donde más caro es: en el VPS, a mitad del aprovisionamiento,
con la base ya creada y el script abortado por `set -e`.

`invoke despliegue` no podía atraparlo: comprueba que las directivas estén,
no que el SQL corra. Esto sí, porque lo ejecuta contra un PostgreSQL real.

Se extrae la consulta del propio script en vez de copiarla aquí: una copia
se queda desactualizada en silencio, y entonces la prueba verifica un SQL
que ya no es el que se envía al servidor.
"""

import re
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

_PROVISION = Path(__file__).resolve().parents[2] / "deploy" / "provision.sh"


def _consulta_del_locale() -> str:
    """La consulta de CA-16 tal cual viaja en el script."""
    texto = _PROVISION.read_text(encoding="utf-8")
    encontrada = re.search(r'"(SELECT datlocprovider.*?)"', texto, re.DOTALL)
    assert encontrada, "no se encontro la consulta del locale en deploy/provision.sh"
    # `${BASE}` es la unica interpolacion de shell que lleva.
    return encontrada.group(1).replace("${BASE}", "postgres")


def test_the_locale_query_runs_against_a_real_postgres(database_url: str) -> None:
    """CA-16: la consulta que verifica el proveedor ICU es ejecutable.

    Se afirma que **corre**, no qué devuelve: el valor depende de cómo se
    creó la base de cada entorno, y esta prueba existe para atrapar el SQL
    inválido, no para replicar la comprobación del aprovisionamiento.
    """
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(_consulta_del_locale())  # type: ignore[arg-type]
        fila = cur.fetchone()

    assert fila is not None
    assert isinstance(fila[0], str)


def test_the_query_reports_provider_and_collation_together(database_url: str) -> None:
    """El formato que el `case` del script compara contra `i es-MX`.

    Si la consulta cambiara y devolviera solo uno de los dos campos, el
    `case` dejaría de coincidir **siempre** y el aprovisionamiento abortaría
    en una base correcta.
    """
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(_consulta_del_locale())  # type: ignore[arg-type]
        fila = cur.fetchone()

    assert fila is not None
    proveedor, _, colacion = str(fila[0]).partition(" ")
    assert proveedor in {"c", "i", "b"}, f"proveedor de locale inesperado: {proveedor!r}"
    assert colacion, "la consulta no devuelve la colacion junto al proveedor"
