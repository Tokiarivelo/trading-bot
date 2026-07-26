"""add decision context to trades

Revision ID: 42463adaeda9
Revises: ad2ce706c70f
Create Date: 2026-07-24 19:33:08.005890

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '42463adaeda9'
down_revision = 'ad2ce706c70f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('trades', sa.Column('reason', sa.String(length=500), server_default='', nullable=False))
    op.add_column('trades', sa.Column('confidence', sa.Float(), nullable=True))
    op.add_column('trades', sa.Column('zone_kind', sa.String(length=16), nullable=True))
    op.add_column('trades', sa.Column('zone_price_low', sa.Float(), nullable=True))
    op.add_column('trades', sa.Column('zone_price_high', sa.Float(), nullable=True))
    op.add_column('trades', sa.Column('zone_time_start', sa.Integer(), nullable=True))
    op.add_column('trades', sa.Column('zone_time_end', sa.Integer(), nullable=True))
    op.add_column('trades', sa.Column('pattern', sa.String(length=64), nullable=True))
    op.add_column('trades', sa.Column('structure', sa.JSON(), server_default='[]', nullable=False))


def downgrade() -> None:
    op.drop_column('trades', 'structure')
    op.drop_column('trades', 'pattern')
    op.drop_column('trades', 'zone_time_end')
    op.drop_column('trades', 'zone_time_start')
    op.drop_column('trades', 'zone_price_high')
    op.drop_column('trades', 'zone_price_low')
    op.drop_column('trades', 'zone_kind')
    op.drop_column('trades', 'confidence')
    op.drop_column('trades', 'reason')
