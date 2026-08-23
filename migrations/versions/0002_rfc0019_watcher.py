"""RFC-0019 watcher heartbeat and lease claim index

Revision ID: 0002_rfc0019_watcher
Revises: 0001_rfc0006_initial_schema
Create Date: 2026-08-23

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_rfc0019_watcher"
down_revision: str | None = "0001_rfc0006_initial_schema"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

# RFC-0019 7.1: una fila por object_key, actualizada en sitio. El latido no
# se acumula: lo que importa es cuando fue la ultima vez, no cuantas hubo.
#
# last_run_at se escribe SIEMPRE; last_success_at solo cuando el ciclo termina
# bien. La alerta de RFC-0010 mira last_success_at -- un sondeo que se dispara
# puntualmente y falla en todos los intentos es igual de grave que uno que no
# se dispara, y mirando last_run_at pareceria sano.
_WATCHER_HEARTBEAT = """
CREATE TABLE watcher_heartbeat (
    object_key      TEXT        PRIMARY KEY,
    last_run_at     TIMESTAMPTZ NOT NULL,
    last_success_at TIMESTAMPTZ,
    last_outcome    TEXT        NOT NULL,
    detail          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT ck_watcher_outcome CHECK (
        last_outcome IN ('no_change','indexed','unstable','missing_corpus','failed')
    )
);
"""

# RFC-0019 5, A-15: la consulta de reclamacion filtra por job_state y por
# lease_expires_at, y desempata por created_at. RFC-0019 daba este indice por
# existente y no existia -- sobre ingestion_jobs no habia mas indices que los
# implicitos de la PK y de las dos UNIQUE (DoR, PR #56, M-1).
_CLAIM_INDEX = """
CREATE INDEX ingestion_jobs_claim_idx
    ON ingestion_jobs (job_state, lease_expires_at, created_at);
"""


def upgrade() -> None:
    op.execute(_WATCHER_HEARTBEAT)
    op.execute(_CLAIM_INDEX)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ingestion_jobs_claim_idx")
    op.execute("DROP TABLE IF EXISTS watcher_heartbeat")
