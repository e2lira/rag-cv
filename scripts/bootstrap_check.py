"""Pasos 2-5 del bootstrap de DEV: extension, base de datos, extensiones y
verificacion de la configuracion regional.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #7.
Invocado desde scripts/bootstrap-dev.ps1. Toda la logica sustantiva vive en
app/core/db_bootstrap.py, ya probada; este script solo orquesta y reporta.
"""

import os
import sys
from urllib.parse import urlsplit, urlunsplit

import psycopg
from dotenv import load_dotenv

from app.core.db_bootstrap import (
    ExtensionUnavailableError,
    SpanishTextSearchMisconfigured,
    bootstrap_spanish_search_extensions,
    ensure_database_with_spanish_locale,
    ensure_extension_available,
    verify_spanish_text_search,
)


def _database_url(maintenance_url: str, db_name: str) -> str:
    parts = urlsplit(maintenance_url)
    return urlunsplit(parts._replace(path=f"/{db_name}"))


def main() -> int:
    load_dotenv()
    maintenance_url = os.environ["DATABASE_MAINTENANCE_URL"]
    db_name = "ragcv"

    # Una conexion por paso, deliberadamente: encadenar operaciones de
    # mantenimiento (SELECT, luego CREATE DATABASE) en la misma conexion
    # deja la segunda atascada en una transaccion que autocommit no puede
    # cambiar. Cada paso abre la suya y la cierra.
    try:
        print("[2/10] Verificando que la extension 'vector' este disponible...")
        with psycopg.connect(maintenance_url) as maint_conn:
            ensure_extension_available(maint_conn, "vector")
        print("        vector disponible.")
    except ExtensionUnavailableError as exc:
        print(f"ERROR [2/10]: {exc}", file=sys.stderr)
        return 1

    print(f"[3/10] Asegurando la base de datos '{db_name}' (locale es-MX)...")
    with psycopg.connect(maintenance_url) as maint_conn:
        created = ensure_database_with_spanish_locale(maint_conn, db_name)
    print(f"        {'creada' if created else 'ya existia'}.")

    db_url = _database_url(maintenance_url, db_name)
    with psycopg.connect(db_url) as conn:
        print("[4/10] Creando extensiones (vector, unaccent, pg_trgm, es_unaccent)...")
        bootstrap_spanish_search_extensions(conn)
        conn.commit()
        print("        extensiones listas.")

        print("[5/10] Verificando la configuracion de texto en espanol...")
        try:
            verify_spanish_text_search(conn)
        except SpanishTextSearchMisconfigured as exc:
            print(f"ERROR [5/10]: {exc}", file=sys.stderr)
            return 1
        print("        busqueda en espanol funciona igual que en Linux.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
