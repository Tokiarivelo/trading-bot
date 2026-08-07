"""regime tagging + transaction cost

Per-decision/trade market-regime tag (volatility bucket, volatility
percentile, trend/range, ADX, trading session) and per-trade transaction
cost, backing the regime-split analytics and cost-as-%-of-gross-edge metric
in OBSERVABILITY_PLAN.md Phase 6 (Pass A). All columns are nullable: rows
written before this migration were never tagged, and "not tagged" has to
stay distinguishable from a real bucket value.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-07 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'b4c5d6e7f8a9'
down_revision = 'a3b4c5d6e7f8'
branch_labels = None
depends_on = None

_REGIME_COLUMNS = (
    ('regime_volatility', sa.String(length=16)),
    ('regime_volatility_percentile', sa.Float()),
    ('regime_trend', sa.String(length=16)),
    ('regime_adx', sa.Float()),
    ('regime_session', sa.String(length=16)),
)

_TRADES_ONLY_COLUMNS = (
    ('transaction_cost', sa.Float()),
)


def upgrade() -> None:
    for name, column_type in _REGIME_COLUMNS:
        op.add_column('trades', sa.Column(name, column_type, nullable=True))
        op.add_column('signal_decisions', sa.Column(name, column_type, nullable=True))
    for name, column_type in _TRADES_ONLY_COLUMNS:
        op.add_column('trades', sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_TRADES_ONLY_COLUMNS):
        op.drop_column('trades', name)
    for name, _ in reversed(_REGIME_COLUMNS):
        op.drop_column('signal_decisions', name)
        op.drop_column('trades', name)
