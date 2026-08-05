"""trades execution telemetry + excursion

Per-trade execution quality (requested price, signed slippage, signal->ack
latency, broker return code) and MFE/MAE excursion, backing the cost- and
excursion-aware analytics in OBSERVABILITY_PLAN.md Phase 3. All columns are
nullable: trades journaled before this migration were never measured, and
"not measured" has to stay distinguishable from a real zero.

Revision ID: d9e0f1a2b3c4
Revises: c8d2e3f4a5b6
Create Date: 2026-08-05 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'd9e0f1a2b3c4'
down_revision = 'c8d2e3f4a5b6'
branch_labels = None
depends_on = None

_COLUMNS = (
    ('requested_price', sa.Float()),
    ('slippage', sa.Float()),
    ('execution_latency_ms', sa.Float()),
    ('broker_retcode', sa.Integer()),
    ('mfe', sa.Float()),
    ('mae', sa.Float()),
)


def upgrade() -> None:
    for name, column_type in _COLUMNS:
        op.add_column('trades', sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.drop_column('trades', name)
