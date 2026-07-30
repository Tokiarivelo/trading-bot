"""add composite account symbol close index to trades

Revision ID: 8dcb0a322997
Revises: 42463adaeda9
Create Date: 2026-07-29 08:40:12.172036

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '8dcb0a322997'
down_revision = '42463adaeda9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        op.f('ix_trades_account_symbol_close'),
        'trades',
        ['account_id', 'symbol', 'close_time'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_trades_account_symbol_close'), table_name='trades')
