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
    raise NotImplementedError
