"""symbol specs table

Revision ID: a1e2aa0bec8a
Revises: 9ae65ef97d1d
Create Date: 2026-07-13 11:28:24.518892

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'a1e2aa0bec8a'
down_revision = '9ae65ef97d1d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'symbol_specs',
        sa.Column('symbol', sa.String(length=64), nullable=False),
        sa.Column('point', sa.Float(), nullable=False),
        sa.Column('digits', sa.Integer(), nullable=False),
        sa.Column('stops_level', sa.Integer(), nullable=False),
        sa.Column('contract_size', sa.Float(), nullable=False),
        sa.Column('volume_min', sa.Float(), nullable=False),
        sa.Column('volume_max', sa.Float(), nullable=False),
        sa.Column('volume_step', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('symbol'),
    )


def downgrade() -> None:
    op.drop_table('symbol_specs')
