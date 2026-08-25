"""RFC-0020 §6: el despliegue lee `DATABASE_URL` sin interpretar el `.env`.

El `.env` lo lee `pydantic`, que tiene sus reglas de parseo. El despliegue lo
pasaba ademas por `source` de bash, que tiene otras. Un archivo valido para
uno puede romper en el otro **en silencio y a mitad del despliegue**: basta
un valor con espacios sin comillas -- `WATCHER_CADENCE=*/5 * * * *` -- para
que bash intente ejecutarlo como comando.

Depender de `source` significa que cualquier variable futura puede romper la
migracion sin tocar el codigo. Se lee solo la linea que hace falta.
"""

import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "deploy.sh"

_ENV_HOSTIL = textwrap.dedent(
    """\
    APP_ENV=qa
    DATABASE_URL=postgresql://ragcv:cl4ve@127.0.0.1:5432/ragcv
    WATCHER_CADENCE=*/5 * * * *
    API_KEYS_JSON={"keys":[{"id":"demo","hash":"abc","active":true}]}
    RUTA=/var/backups y algo mas
    """
)


def _extraer(env: Path) -> subprocess.CompletedProcess[str]:
    funcion = subprocess.run(
        ["sed", "-n", "/^_url_de_la_base_del_env/,/^}/p", str(_DEPLOY)],
        capture_output=True,
        text=True,
    ).stdout
    guion = f'{funcion}\n_url_de_la_base_del_env "{env}"\n'
    return subprocess.run(["bash", "-c", guion], capture_output=True, text=True, errors="replace")


def test_reads_the_url_without_executing_the_rest(tmp_path: Path) -> None:
    """Un `.env` con valores hostiles no impide leer la URL.

    Las tres lineas de abajo rompen `source`: espacios sin comillas,
    asteriscos que el shell expande, y llaves que abren un grupo.
    """
    env = tmp_path / ".env"
    env.write_text(_ENV_HOSTIL, encoding="utf-8")

    resultado = _extraer(env)

    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "postgresql://ragcv:cl4ve@127.0.0.1:5432/ragcv"
    assert "command not found" not in resultado.stderr


def test_quotes_around_the_value_are_stripped(tmp_path: Path) -> None:
    """Entrecomillar es legitimo en un `.env`, y no debe llegar a la URL."""
    env = tmp_path / ".env"
    env.write_text('DATABASE_URL="postgresql://a:b@127.0.0.1:5432/c"\n', encoding="utf-8")

    resultado = _extraer(env)

    assert resultado.stdout.strip() == "postgresql://a:b@127.0.0.1:5432/c"


def test_it_fails_loudly_when_the_variable_is_missing(tmp_path: Path) -> None:
    """Sin `DATABASE_URL`, aborta nombrandola.

    Migrar con una URL vacia apuntaria a una base equivocada o fallaria con
    un mensaje sin relacion. El contrato se impone abortando.
    """
    env = tmp_path / ".env"
    env.write_text("APP_ENV=qa\n", encoding="utf-8")

    resultado = _extraer(env)

    assert resultado.returncode != 0
    assert "DATABASE_URL" in resultado.stdout + resultado.stderr
