"""Aprovisionamiento de la base de datos de desarrollo y de prueba.

Contrato normativo: docs/rfc/RFC-0011-entorno-dev-windows-nativo.md #4.2, #4.3.
Compartido entre el bootstrap real (ragcv) y las bases efimeras de prueba
(ragcv_test_<pid>): misma sentencia CREATE DATABASE, misma configuracion
regional -- si difieren, las pruebas de busqueda lexica mienten (RFC-0011 #8).
"""

import psycopg
from psycopg import sql


class ExtensionUnavailableError(RuntimeError):
    """La extension no esta disponible en el servidor -- ver RFC-0011 #4.2."""


def ensure_extension_available(conn: psycopg.Connection, extension_name: str) -> None:
    """Solo lectura: en autocommit para no dejar la conexion en transaccion
    si quien llama la reutiliza despues para un CREATE DATABASE."""
    conn.autocommit = True
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


def database_exists(maintenance_conn: psycopg.Connection, db_name: str) -> bool:
    with maintenance_conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
        return cur.fetchone() is not None


def ensure_database_with_spanish_locale(maintenance_conn: psycopg.Connection, db_name: str) -> bool:
    """Crea la base si no existe. Devuelve True si la creo, False si ya existia.

    CREATE DATABASE no acepta IF NOT EXISTS en PostgreSQL -- este chequeo
    previo es lo que hace posible correr el bootstrap dos veces (CA-1).
    """
    maintenance_conn.autocommit = True  # database_exists() abriria una
    # transaccion en modo por defecto, y CREATE DATABASE no puede correr
    # dentro de una transaccion ya iniciada.
    if database_exists(maintenance_conn, db_name):
        return False
    create_database_with_spanish_locale(maintenance_conn, db_name)
    return True


def create_database_with_spanish_locale(maintenance_conn: psycopg.Connection, db_name: str) -> None:
    """CREATE DATABASE con proveedor ICU es-MX -- RFC-0011 #4.3.

    Requiere una conexion en autocommit: CREATE DATABASE no puede correr
    dentro de una transaccion.
    """
    maintenance_conn.autocommit = True
    with maintenance_conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "CREATE DATABASE {} WITH ENCODING 'UTF8' "
                "LOCALE_PROVIDER = 'icu' ICU_LOCALE = 'es-MX' TEMPLATE = template0"
            ).format(sql.Identifier(db_name))
        )


def bootstrap_spanish_search_extensions(conn: psycopg.Connection) -> None:
    """vector, unaccent, pg_trgm y la configuracion es_unaccent -- RFC-0011 #4.3.

    El bloque de es_unaccent es identico, palabra por palabra, al de
    infra/sql/001_initialize_rag_cv.sql (RFC-0006): es deliberado, para que
    ese script lo vuelva a aplicar como no-op idempotente, no como una
    segunda fuente de verdad.
    """
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cur.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_ts_config AS config
                    JOIN pg_namespace AS namespace ON namespace.oid = config.cfgnamespace
                    WHERE namespace.nspname = 'public'
                      AND config.cfgname = 'es_unaccent'
                ) THEN
                    CREATE TEXT SEARCH CONFIGURATION public.es_unaccent (COPY = spanish);
                END IF;
            END;
            $$;
            """
        )
        cur.execute(
            "ALTER TEXT SEARCH CONFIGURATION public.es_unaccent "
            "ALTER MAPPING FOR hword, hword_part, word WITH unaccent, spanish_stem"
        )


class SpanishTextSearchMisconfigured(RuntimeError):
    """La configuracion regional no reconoce los acentuados como letras --
    ver RFC-0011 #4.3. Es un fallo silencioso si no se prueba."""


def verify_spanish_text_search(conn: psycopg.Connection) -> None:
    """Las dos consultas de RFC-0011 #4.3, tal cual. No se asume: se prueba
    en cada bootstrap, porque el fallo es silencioso si no se prueba."""
    with conn.cursor() as cur:
        try:
            cur.execute("SELECT to_tsvector('es_unaccent', 'Informática Ingeniería')")
        except psycopg.errors.UndefinedObject as exc:
            raise SpanishTextSearchMisconfigured(
                "La configuracion de busqueda 'es_unaccent' no existe. "
                "Corre bootstrap_spanish_search_extensions() -- RFC-0011 #4.3."
            ) from exc
        row = cur.fetchone()
        assert row is not None  # SELECT sin FROM siempre devuelve una fila
        (lexemes,) = row
        if "'informat':1" not in lexemes or "'ingenieri':2" not in lexemes:
            raise SpanishTextSearchMisconfigured(
                f"La configuracion regional produce lexemas inesperados: {lexemes!r}. "
                "Revisa el proveedor ICU y el locale es-MX -- RFC-0011 #4.3."
            )

        cur.execute(
            "SELECT to_tsvector('es_unaccent', %s) @@ websearch_to_tsquery('es_unaccent', %s)",
            ("informática", "informatica"),
        )
        row = cur.fetchone()
        assert row is not None  # SELECT sin FROM siempre devuelve una fila
        (found,) = row
        if not found:
            raise SpanishTextSearchMisconfigured(
                "La busqueda sin tilde no encuentra el termino acentuado. "
                "RFC-0011 #4.3: el clasificador no reconoce los acentuados como letras."
            )


def drop_database_force(maintenance_conn: psycopg.Connection, db_name: str) -> None:
    """DROP DATABASE ... WITH (FORCE): elimina aunque queden conexiones abiertas.

    Es lo que permite que la limpieza se complete incluso si un test que
    fallo dejo una conexion colgada (RFC-0011 CA-10).
    """
    maintenance_conn.autocommit = True
    with maintenance_conn.cursor() as cur:
        cur.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(db_name))
        )
