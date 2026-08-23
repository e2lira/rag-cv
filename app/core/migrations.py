"""Resolucion del head de Alembic en tiempo de ejecucion -- RFC-0021 6."""

from pathlib import Path


def resolve_expected_head(alembic_ini_path: Path | None = None) -> str:
    raise NotImplementedError
