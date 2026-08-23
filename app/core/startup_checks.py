"""Comprobaciones de arranque -- RFC-0006 7."""

import psycopg


class StartupCheckError(RuntimeError):
    """Aborta el arranque de la aplicacion -- RFC-0006 7."""


def check_embedding_dimension(conn: psycopg.Connection, expected_dim: int) -> None:
    raise NotImplementedError


def check_single_embed_model(conn: psycopg.Connection, expected_model_id: str) -> None:
    raise NotImplementedError
