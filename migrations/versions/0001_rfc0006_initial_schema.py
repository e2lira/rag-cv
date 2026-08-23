"""RFC-0006 initial schema

Revision ID: 0001_rfc0006_initial_schema
Revises:
Create Date: 2026-08-23

"""
from collections.abc import Sequence

revision: str = "0001_rfc0006_initial_schema"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    raise NotImplementedError("RFC-0006 CA-1: el esquema de la 4 aun no esta implementado")


def downgrade() -> None:
    raise NotImplementedError("RFC-0006 CA-1: el esquema de la 4 aun no esta implementado")
