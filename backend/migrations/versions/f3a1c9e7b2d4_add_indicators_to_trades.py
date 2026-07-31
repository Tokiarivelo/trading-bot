"""add indicators to trades

Revision ID: f3a1c9e7b2d4
Revises: 8dcb0a322997
Create Date: 2026-07-30 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'f3a1c9e7b2d4'
down_revision = '8dcb0a322997'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trades', sa.Column('indicators', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('trades', 'indicators')
