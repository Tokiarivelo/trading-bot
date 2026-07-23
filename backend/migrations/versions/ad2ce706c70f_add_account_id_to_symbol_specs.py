"""add account_id to symbol_specs

Revision ID: ad2ce706c70f
Revises: 1ec3d9e05ff1
Create Date: 2026-07-23 00:00:04.000000

Same reasoning as the candles migration: broker-specific symbol facts
(point/digits/stops_level/...) must not be shared across accounts, so
`account_id` joins the primary key rather than being a plain indexed column.
"""
from __future__ import annotations

import warnings

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import SAWarning


revision = 'ad2ce706c70f'
down_revision = '1ec3d9e05ff1'
branch_labels = None
depends_on = None

_DEFAULT_ACCOUNT_ID = 'default'


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', category=SAWarning)
        with op.batch_alter_table('symbol_specs', recreate='always') as batch_op:
            batch_op.add_column(
                sa.Column(
                    'account_id',
                    sa.String(length=64),
                    server_default=_DEFAULT_ACCOUNT_ID,
                    nullable=False,
                )
            )
            batch_op.create_primary_key('pk_symbol_specs', ['account_id', 'symbol'])


def downgrade() -> None:
    with op.batch_alter_table('symbol_specs', recreate='always') as batch_op:
        batch_op.drop_column('account_id')
        batch_op.create_primary_key('pk_symbol_specs', ['symbol'])
