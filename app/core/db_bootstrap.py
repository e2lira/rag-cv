"""Aprovisionamiento de la base de datos de desarrollo y de prueba.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #4.2, #4.3.
Compartido entre el bootstrap real (ragcv) y las bases efimeras de prueba
(ragcv_test_<pid>): misma sentencia CREATE DATABASE, misma configuracion
regional -- si difieren, las pruebas de busqueda lexica mienten (RFC-0011 #8).
"""

import psycopg


class ExtensionUnavailableError(RuntimeError):
    """La extension no esta disponible en el servidor -- ver RFC-0011 #4.2."""


def ensure_extension_available(conn: psycopg.Connection, extension_name: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM pg_available_extensions WHERE name = %s",
            (extension_name,),
        )
        if cur.fetchone() is None:
            raise ExtensionUnavailableError(
                f"La extension '{extension_name}' no esta disponible en este servidor "
                f"de PostgreSQL. Sigue las instrucciones de compilacion de "
                f"RFC-0011 #4.2 (docs/rfc/RFC-0011-entorno-dev-windows-nativo.md)."
            )


def create_database_with_spanish_locale(
    maintenance_conn: psycopg.Connection, db_name: str
) -> None:
    raise NotImplementedError


def bootstrap_spanish_search_extensions(conn: psycopg.Connection) -> None:
    raise NotImplementedError


def drop_database_force(maintenance_conn: psycopg.Connection, db_name: str) -> None:
    raise NotImplementedError
