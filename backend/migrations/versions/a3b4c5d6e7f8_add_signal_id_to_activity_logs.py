"""add signal_id to activity_logs

Correlation id (OBSERVABILITY_PLAN.md Phase 5): joins every log line from
signal -> sizing -> order -> fill -> journal together, so `GET
/activity/history?signal_id=...` can read one signal's whole life in order.
Nullable — most log lines (health checks, candle polling, ...) are emitted
outside any signal's processing window and carry no signal id.

Revision ID: a3b4c5d6e7f8
Revises: d9e0f1a2b3c4
Create Date: 2026-08-06 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'a3b4c5d6e7f8'
down_revision = 'd9e0f1a2b3c4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'activity_logs',
        sa.Column('signal_id', sa.String(length=32), nullable=True),
    )
    op.create_index(
        op.f('ix_activity_logs_signal_id'), 'activity_logs', ['signal_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_activity_logs_signal_id'), table_name='activity_logs')
    op.drop_column('activity_logs', 'signal_id')
