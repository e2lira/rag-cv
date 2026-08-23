"""RFC-0019 watcher outcome gains dead_lettered

Revision ID: 0003_rfc0019_dead_lettered
Revises: 0002_rfc0019_watcher
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_rfc0019_dead_lettered"
down_revision: str | None = "0002_rfc0019_watcher"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# RFC-0019 7.1: 'dead_lettered' NO es un sinonimo de 'failed'. Un fallo
# transitorio se reintenta solo en el ciclo siguiente; un contenido que agoto
# WATCHER_MAX_ATTEMPTS espera intervencion humana y no se arregla esperando.
# Son dos acciones distintas del runbook, y la alerta de RFC-0010 no puede
# separarlas si el latido las escribe con la misma palabra.
_SIX_OUTCOMES = """
ALTER TABLE watcher_heartbeat DROP CONSTRAINT ck_watcher_outcome;
ALTER TABLE watcher_heartbeat ADD CONSTRAINT ck_watcher_outcome CHECK (
    last_outcome IN ('no_change','indexed','unstable',
                     'missing_corpus','failed','dead_lettered')
);
"""

# La vuelta atras solo es posible si ninguna fila usa ya el valor nuevo: el
# CHECK antiguo la rechazaria. Se normaliza a 'failed', que es lo que este
# valor significaba antes de existir.
_FIVE_OUTCOMES = """
UPDATE watcher_heartbeat SET last_outcome = 'failed'
    WHERE last_outcome = 'dead_lettered';
ALTER TABLE watcher_heartbeat DROP CONSTRAINT ck_watcher_outcome;
ALTER TABLE watcher_heartbeat ADD CONSTRAINT ck_watcher_outcome CHECK (
    last_outcome IN ('no_change','indexed','unstable','missing_corpus','failed')
);
"""


def upgrade() -> None:
    op.execute(_SIX_OUTCOMES)


def downgrade() -> None:
    op.execute(_FIVE_OUTCOMES)
