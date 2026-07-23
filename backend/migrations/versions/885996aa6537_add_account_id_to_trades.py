"""add account_id to trades

Revision ID: 885996aa6537
Revises: 7296ba2cc26a
Create Date: 2026-07-23 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '885996aa6537'
down_revision = '7296ba2cc26a'
branch_labels = None
depends_on = None

# Every row in this table predates multi-account support (MULTI_ACCOUNT_PLAN.md
# Phase 4) and was traded on the sole account configured back then — the
# `default` entry in configs/accounts.yaml.
_DEFAULT_ACCOUNT_ID = 'default'


def upgrade() -> None:
    op.add_column(
        'trades',
        sa.Column(
            'account_id', sa.String(length=64), server_default=_DEFAULT_ACCOUNT_ID, nullable=False
        ),
    )
    op.create_index(op.f('ix_trades_account_id'), 'trades', ['account_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trades_account_id'), table_name='trades')
    op.drop_column('trades', 'account_id')
