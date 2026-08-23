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


_PY_PATHS = "app/ tests/ tasks.py"


@task
def lint(c):
    # Acotado a codigo Python: "ruff format ." tambien reformatea los
    # bloques de codigo dentro de los RFC en Markdown, que son documentos
    # aprobados y no se tocan fuera del proceso ADU.
    c.run(f"ruff check {_PY_PATHS}")
    c.run(f"ruff format --check {_PY_PATHS}")
    c.run("mypy app/")


@task
def test(c, kind="unit"):
    c.run(f"pytest -m {kind}")


@task
def evals(c, suite="pr"):
    c.run(f"python evals/run_eval.py --suite {suite}")
