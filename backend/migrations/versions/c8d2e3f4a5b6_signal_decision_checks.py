"""signal_decisions.checks

Structured per-gate check capture on the typed decision trail — each row now
carries the `(name, value, threshold, comparison, passed)` tuples the engine
evaluated on its way from signal to fill, backing the veto funnel
(OBSERVABILITY_PLAN.md Phase 2). Existing rows get an empty list.

Revision ID: c8d2e3f4a5b6
Revises: b7c1d2e3f4a5
Create Date: 2026-08-05 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'c8d2e3f4a5b6'
down_revision = 'b7c1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'signal_decisions',
        sa.Column('checks', sa.JSON(), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    op.drop_column('signal_decisions', 'checks')
