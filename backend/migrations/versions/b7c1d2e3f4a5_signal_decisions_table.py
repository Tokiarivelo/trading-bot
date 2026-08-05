"""signal_decisions table

Typed decision trail written directly by the engine/order service, replacing
the regex log-scrape as the source of truth for a bot's signal→outcome trail
(OBSERVABILITY_PLAN.md Phase 1).

Revision ID: b7c1d2e3f4a5
Revises: a1b2c3d4e5f6
Create Date: 2026-08-05 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'b7c1d2e3f4a5'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'signal_decisions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('signal_id', sa.String(length=36), nullable=False),
        sa.Column('account_id', sa.String(length=64), nullable=False),
        sa.Column('bot', sa.String(length=255), nullable=False),
        sa.Column('strategy', sa.String(length=128), nullable=False),
        sa.Column('symbol', sa.String(length=64), nullable=False),
        sa.Column('timeframe', sa.String(length=8), nullable=False),
        sa.Column('direction', sa.String(length=8), nullable=False),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('created_at', sa.Integer(), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_signal_decisions_signal_id'), 'signal_decisions', ['signal_id'], unique=True
    )
    op.create_index(
        op.f('ix_signal_decisions_account_id'), 'signal_decisions', ['account_id'], unique=False
    )
    op.create_index(op.f('ix_signal_decisions_bot'), 'signal_decisions', ['bot'], unique=False)
    op.create_index(
        op.f('ix_signal_decisions_symbol'), 'signal_decisions', ['symbol'], unique=False
    )
    op.create_index(
        op.f('ix_signal_decisions_created_at'), 'signal_decisions', ['created_at'], unique=False
    )
    op.create_index(
        op.f('ix_signal_decisions_outcome'), 'signal_decisions', ['outcome'], unique=False
    )
    op.create_index(
        'ix_signal_decisions_account_bot_created',
        'signal_decisions',
        ['account_id', 'bot', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_signal_decisions_account_bot_created', table_name='signal_decisions')
    op.drop_index(op.f('ix_signal_decisions_outcome'), table_name='signal_decisions')
    op.drop_index(op.f('ix_signal_decisions_created_at'), table_name='signal_decisions')
    op.drop_index(op.f('ix_signal_decisions_symbol'), table_name='signal_decisions')
    op.drop_index(op.f('ix_signal_decisions_bot'), table_name='signal_decisions')
    op.drop_index(op.f('ix_signal_decisions_account_id'), table_name='signal_decisions')
    op.drop_index(op.f('ix_signal_decisions_signal_id'), table_name='signal_decisions')
    op.drop_table('signal_decisions')
