"""add account_id to candles

Revision ID: 1ec3d9e05ff1
Revises: ab579974226c
Create Date: 2026-07-23 00:00:03.000000

Different brokers quote different spreads/point-values/digits for a
nominally identical symbol (e.g. `XAUUSD` vs `XAUUSD.a`), so `account_id`
joins the primary key rather than being a plain indexed column — a shared
cache keyed only on (symbol, timeframe, time) would silently mix
broker-specific price history across accounts (MULTI_ACCOUNT_PLAN.md Phase 4).
SQLite can't ALTER a primary key in place, so this widens it via Alembic's
batch (table-recreate) mode.
"""
from __future__ import annotations

import warnings

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import SAWarning


revision = '1ec3d9e05ff1'
down_revision = 'ab579974226c'
branch_labels = None
depends_on = None

_DEFAULT_ACCOUNT_ID = 'default'


def upgrade() -> None:
    with warnings.catch_warnings():
        # Expected: the reflected table's old (symbol, timeframe, time)
        # primary key is superseded by the new named one below.
        warnings.simplefilter('ignore', category=SAWarning)
        with op.batch_alter_table('candles', recreate='always') as batch_op:
            batch_op.add_column(
                sa.Column(
                    'account_id',
                    sa.String(length=64),
                    server_default=_DEFAULT_ACCOUNT_ID,
                    nullable=False,
                )
            )
            batch_op.create_primary_key(
                'pk_candles', ['account_id', 'symbol', 'timeframe', 'time']
            )


def downgrade() -> None:
    with op.batch_alter_table('candles', recreate='always') as batch_op:
        batch_op.drop_column('account_id')
        batch_op.create_primary_key('pk_candles', ['symbol', 'timeframe', 'time'])
