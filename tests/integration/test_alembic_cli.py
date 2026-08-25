"""RFC-0006: `alembic upgrade head` funciona desde la linea de comandos.

`alembic.ini` no define `sqlalchemy.url`, y `tests/conftest.py` la inyecta en
memoria con `cfg.set_main_option(...)`. Consecuencia: la suite entera pasaba
en verde y **el binario de `alembic` nunca habia funcionado**, porque nadie
lo ejecutaba como lo ejecuta el despliegue.

El sintoma aparecio en el VPS, a mitad del despliegue:

    File "migrations/env.py", line 20, in run_migrations_online
      connectable = engine_from_config(...)
    KeyError: 'url'

Esta prueba invoca el **binario**, en un subproceso, con el entorno que tiene
el servidor -- que es la unica forma de ejercitar el camino que usa
`deploy/deploy.sh`. Llamar a `command.upgrade()` desde Python no lo cubre: es
justamente lo que la suite ya hacia cuando el binario estaba roto.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

_RAIZ = Path(__file__).resolve().parents[2]


def test_alembic_upgrade_works_from_the_command_line(database_url: str) -> None:
    """El binario resuelve la URL desde el entorno, como en el despliegue.

    `database_url` ya trae la base efimera migrada por el `conftest`; que
    `upgrade head` vuelva a correr sobre ella es idempotente y lo que
    importa es que **arranque y termine**, no que aplique algo.
    """
    entorno = {**os.environ, "DATABASE_URL": database_url}

    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_RAIZ,
        env=entorno,
        capture_output=True,
        text=True,
        errors="replace",
    )

    assert resultado.returncode == 0, (
        "alembic desde la linea de comandos fallo:\n"
        f"stdout:\n{resultado.stdout}\nstderr:\n{resultado.stderr}"
    )


def test_alembic_says_which_variable_falta_si_no_hay_url() -> None:
    """Sin `DATABASE_URL`, el fallo tiene que nombrar la variable.

    El `KeyError: 'url'` original no decia nada util: mandaba a mirar
    `alembic.ini` cuando lo que faltaba era una variable de entorno. Un
    mensaje que no nombra la causa cuesta mas que el fallo.
    """
    entorno = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}

    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_RAIZ,
        env=entorno,
        capture_output=True,
        text=True,
        errors="replace",
    )

    assert resultado.returncode != 0
    assert "DATABASE_URL" in resultado.stdout + resultado.stderr, (
        "el fallo no nombra DATABASE_URL:\n" + resultado.stdout + resultado.stderr
    )
