"""add account_id to strategy_versions

Revision ID: ab579974226c
Revises: d6d6e88aac6c
Create Date: 2026-07-23 00:00:02.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'ab579974226c'
down_revision = 'd6d6e88aac6c'
branch_labels = None
depends_on = None

_DEFAULT_ACCOUNT_ID = 'default'


def upgrade() -> None:
    op.add_column(
        'strategy_versions',
        sa.Column(
            'account_id', sa.String(length=64), server_default=_DEFAULT_ACCOUNT_ID, nullable=False
        ),
    )
    op.create_index(
        op.f('ix_strategy_versions_account_id'), 'strategy_versions', ['account_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_strategy_versions_account_id'), table_name='strategy_versions')
    op.drop_column('strategy_versions', 'account_id')
