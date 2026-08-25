from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _url_de_la_base() -> str:
    """La URL de la base, de la configuracion de alembic o de `Settings`.

    `alembic.ini` **no** define `sqlalchemy.url` a proposito: la credencial
    va embebida en la URL y no se versiona. Quien la inyecta depende de
    quien invoca:

    - `tests/conftest.py` la fija en memoria con `cfg.set_main_option(...)`,
      porque cada prueba apunta a una base efimera distinta.
    - La linea de comandos (`alembic upgrade head`, que es lo que ejecuta
      `deploy/deploy.sh`) no fija nada, y aqui se resuelve desde
      `MigrationSettings` -- la capa de configuracion sigue siendo la unica
      que lee el entorno (RFC-0001 #4).

    Se usa `MigrationSettings` y no `Settings`: migrar no puede depender de
    tener las claves de los proveedores de modelo, que no tienen nada que
    ver con el esquema.

    Sin esta rama, el binario fallaba con `KeyError: 'url'` dentro de
    `engine_from_config`, un mensaje que manda a mirar `alembic.ini` cuando
    lo que falta es una variable de entorno.
    """
    de_alembic = config.get_main_option("sqlalchemy.url", None)
    if de_alembic:
        return de_alembic

    from pydantic import ValidationError

    from app.core.settings import MigrationSettings

    try:
        cruda = MigrationSettings().database_url.get_secret_value()
        # `psycopg` usa el esquema `postgresql://`; SQLAlchemy necesita el
        # driver explicito o cae en `psycopg2`, que este proyecto no instala
        # -- y el fallo aparece como un `ModuleNotFoundError` que no tiene
        # nada que ver con la migracion. Mismo criterio que `tests/conftest.py`.
        return cruda.replace("postgresql://", "postgresql+psycopg://", 1)
    except ValidationError as exc:
        # Se nombra la variable: un fallo que no dice cual falta cuesta mas
        # que el fallo mismo, y este aparece a mitad de un despliegue.
        raise RuntimeError(
            "alembic no encontro la URL de la base. Define DATABASE_URL en el "
            "entorno (o en el .env que cargue el proceso) antes de migrar."
        ) from exc


def run_migrations_offline() -> None:
    context.configure(
        url=_url_de_la_base(), literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    seccion = dict(config.get_section(config.config_ini_section, {}))
    seccion["sqlalchemy.url"] = _url_de_la_base()
    connectable = engine_from_config(seccion, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
