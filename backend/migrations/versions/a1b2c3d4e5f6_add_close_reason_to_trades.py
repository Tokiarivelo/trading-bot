"""add close_reason to trades

Revision ID: a1b2c3d4e5f6
Revises: e0763aef2056
Create Date: 2026-08-05 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = 'e0763aef2056'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trades', sa.Column('close_reason', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('trades', 'close_reason')
