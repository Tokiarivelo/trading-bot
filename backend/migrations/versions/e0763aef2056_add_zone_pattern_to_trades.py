"""add zone_pattern to trades

Revision ID: e0763aef2056
Revises: f3a1c9e7b2d4
Create Date: 2026-07-31 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'e0763aef2056'
down_revision = 'f3a1c9e7b2d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trades', sa.Column('zone_pattern', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('trades', 'zone_pattern')
