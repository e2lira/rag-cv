"""Tareas multiplataforma, un unico comando en Windows, Ubuntu y en el CI.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #6.
Windows no tiene `make`; mantener Makefile + .ps1 en paralelo garantiza que
uno de los dos se quede obsoleto.

db_up, index y evals apuntan a modulos de RFCs que todavia no existen
(RFC-0006, RFC-0002, RFC-0009): fallan si se invocan hoy, y eso es
esperado, no un error de este archivo.

Desviacion declarada respecto al contrato literal de #6: `lint` no incluye
todavia `lint-imports`. Import-linter necesita un contrato de capas
(Domain/Application/Adapters, RFC-0001) que aun no existe; agregarlo sin
configuracion real rompe `invoke lint` siempre, no solo cuando falta el
RFC que lo habilita -- y CA-12 exige que `invoke lint test` funcione hoy.
Se agrega cuando RFC-0001 defina los limites reales que hay que hacer
cumplir.
"""

import ast
from pathlib import Path

from invoke import task


@task
def db_up(c):
    c.run("alembic upgrade head")


@task
def index(c, force=False):
    c.run(f"python -m app.ingestion.indexer --corpus corpus/cv.md {'--force' if force else ''}")


@task
def dev(c):
    c.run("python -m app.dev_server")


_PY_PATHS = "app/ tests/ scripts/ tasks.py migrations/"


# La unica lectura de entorno permitida (RFC-0001 #4: "Leerse os.environ en
# cualquier otro sitio" figura como prohibido en la tabla de capas).
_LECTOR_DE_ENTORNO = Path("app/core/settings.py")
_LECTURAS_DE_ENTORNO = {"environ", "getenv"}


def _lecturas_de_entorno_fuera_de_settings() -> list[str]:
    """RFC-0001 #4: la capa de configuracion es la unica que lee el entorno.

    Vive en `lint` y no en una prueba porque RFC-0014 #5 exige que una
    prueba `unit` no haga IO, y recorrer el arbol lo es. `lint` ya lo lee
    entero con ruff y mypy, asi que es su sitio.

    Sobre el AST y no con `grep`, para no marcar la palabra `environ` dentro
    de una cadena o de un comentario."""
    hallazgos = []
    for archivo in sorted(Path("app").rglob("*.py")):
        if archivo == _LECTOR_DE_ENTORNO:
            continue
        arbol = ast.parse(archivo.read_text(encoding="utf-8"), filename=str(archivo))
        hallazgos += [
            f"{archivo}:{nodo.lineno} -- os.{nodo.attr} fuera de la capa de configuracion"
            for nodo in ast.walk(arbol)
            if isinstance(nodo, ast.Attribute)
            and nodo.attr in _LECTURAS_DE_ENTORNO
            and isinstance(nodo.value, ast.Name)
            and nodo.value.id == "os"
        ]
    return hallazgos


@task
def prohibiciones(c):
    """Prohibiciones del gate ADU comprobables sobre el arbol (RFC-0001 #4).

    Si esto se pone rojo, la respuesta no es anadir una excepcion: es mover
    la variable a `Settings`, que es donde el RFC dice que vive."""
    hallazgos = _lecturas_de_entorno_fuera_de_settings()
    if hallazgos:
        detalle = "\n  ".join(hallazgos)
        raise SystemExit(f"Prohibiciones del gate ADU incumplidas:\n  {detalle}")


@task
def lint(c):
    # Acotado a codigo Python: "ruff format ." tambien reformatea los
    # bloques de codigo dentro de los RFC en Markdown, que son documentos
    # aprobados y no se tocan fuera del proceso ADU.
    c.run(f"ruff check {_PY_PATHS}")
    c.run(f"ruff format --check {_PY_PATHS}")
    c.run("mypy app/ migrations/")
    prohibiciones(c)


@task
def test(c, kind="unit"):
    c.run(f"pytest -m {kind}")


@task
def evals(c, suite="pr"):
    c.run(f"python evals/run_eval.py --suite {suite}")
