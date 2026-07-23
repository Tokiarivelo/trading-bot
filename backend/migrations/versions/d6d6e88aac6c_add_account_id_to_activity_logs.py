"""add account_id to activity_logs

Revision ID: d6d6e88aac6c
Revises: 885996aa6537
Create Date: 2026-07-23 00:00:01.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'd6d6e88aac6c'
down_revision = '885996aa6537'
branch_labels = None
depends_on = None

_DEFAULT_ACCOUNT_ID = 'default'


def upgrade() -> None:
    op.add_column(
        'activity_logs',
        sa.Column(
            'account_id', sa.String(length=64), server_default=_DEFAULT_ACCOUNT_ID, nullable=False
        ),
    )
    op.create_index(
        op.f('ix_activity_logs_account_id'), 'activity_logs', ['account_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_activity_logs_account_id'), table_name='activity_logs')
    op.drop_column('activity_logs', 'account_id')
