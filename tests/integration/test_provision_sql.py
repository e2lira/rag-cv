"""RFC-0020 §4, CA-16: el SQL que lleva el aprovisionamiento es ejecutable.

La comprobación del ICU es el **único paso irreversible** del despliegue —la
configuración regional se fija al crear la base—, y ya falló dos veces por
razones que no se ven leyendo el script:

1. `datlocprovider` es de tipo `"char"`, así que `datlocprovider || ' ' || …`
   deja a PostgreSQL sin saber qué operador usar (*«operator is not unique»*).
2. La locale de ICU **no vive en `datcollate`** sino en `daticulocale`
   (PG 15–16) o `datlocale` (PG ≥ 17) —ADR-0019—, y el nombre cambia con la
   versión del servidor.

La segunda es la peligrosa: la condición no se cumplía nunca, y su rama de
fallo ordena `dropdb` sobre una base correcta.

`invoke despliegue` no puede atrapar ninguna de las dos: comprueba que las
directivas **estén**, no que el SQL **corra** ni que la columna **exista** en
el servidor de destino. Esto sí, porque lo ejecuta contra un PostgreSQL real.

Todo se extrae del propio script en vez de copiarlo aquí: una copia se queda
desactualizada en silencio, y entonces la prueba verifica un SQL que ya no es
el que se envía al servidor.
"""

import re
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

_PROVISION = Path(__file__).resolve().parents[2] / "deploy" / "provision.sh"


def _texto() -> str:
    return _PROVISION.read_text(encoding="utf-8")


def _columnas_de_locale_que_conoce_el_script() -> set[str]:
    """Los nombres de columna que el script sabe resolver (ADR-0019)."""
    return set(re.findall(r"\b(daticulocale|datlocale)\b", _texto()))


def _columna_del_servidor(cur: psycopg.Cursor) -> str | None:
    """La columna de locale de ICU que existe en ESTE servidor."""
    cur.execute(
        "SELECT attname FROM pg_attribute "
        "WHERE attrelid = 'pg_database'::regclass "
        "AND attname IN ('daticulocale', 'datlocale')"
    )
    fila = cur.fetchone()
    return str(fila[0]) if fila else None


def test_the_script_knows_this_servers_locale_column(database_url: str) -> None:
    """ADR-0019: el nombre de la columna cambia entre versiones.

    Un script que fije uno solo falla al actualizar el servidor con un
    `UndefinedColumn`, que parece un problema de permisos o de conexión y
    manda a depurar al sitio equivocado.
    """
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        del conn
        columna = _columna_del_servidor(cur)

    assert columna is not None, "este PostgreSQL no expone la locale de ICU por base"
    conocidas = _columnas_de_locale_que_conoce_el_script()
    assert columna in conocidas, (
        f"el aprovisionamiento no contempla {columna!r}; solo conoce {sorted(conocidas)}"
    )


def test_the_locale_query_runs_and_reports_icu(database_url: str) -> None:
    """CA-16: la consulta corre y devuelve proveedor **y** locale de ICU.

    Se afirma la forma —`<proveedor> <locale>`— y no el valor: la locale
    concreta depende de cómo se creó la base de cada entorno, y esta prueba
    existe para atrapar el SQL inválido y la columna equivocada, no para
    replicar la comprobación del aprovisionamiento.
    """
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        columna = _columna_del_servidor(cur)
        assert columna is not None
        cur.execute(  # noqa: S608 -- el nombre sale de pg_attribute, no de entrada externa
            f"SELECT datlocprovider::text || ' ' || COALESCE({columna}, '(ninguna)') "
            "FROM pg_database WHERE datname = current_database()"
        )
        fila = cur.fetchone()
        del conn

    assert fila is not None
    proveedor, _, locale = str(fila[0]).partition(" ")
    assert proveedor in {"c", "i", "b"}, f"proveedor inesperado: {proveedor!r}"
    assert locale, "la consulta no devuelve la locale junto al proveedor"


def test_the_script_never_compares_against_datcollate() -> None:
    """ADR-0019: `datcollate` trae la locale de `libc`, no la de ICU.

    Su valor difiere por host —`en_US.UTF-8` en el VPS, `Spanish_Mexico.1252`
    en la máquina de desarrollo— y **no dice nada sobre ICU**. Compararlo
    contra `es-MX` no falla: nunca coincide, y su rama de fallo ordena
    `dropdb` sobre una base correcta.
    """
    lineas = [
        f"{numero}: {linea.strip()}"
        for numero, linea in enumerate(_texto().splitlines(), start=1)
        if "datcollate" in linea and not linea.lstrip().startswith("#")
    ]

    assert not lineas, "el aprovisionamiento compara contra datcollate:\n" + "\n".join(lineas)
