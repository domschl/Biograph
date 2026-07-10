"""add_update_id_column

Revision ID: 80580b8a7125
Revises: 8a72d18ff538
Create Date: 2026-07-10 09:47:39.513293

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80580b8a7125'
down_revision: Union[str, None] = '8a72d18ff538'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('update_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_events_update_id'), 'events', ['update_id'], unique=False)
    op.execute("UPDATE events SET update_id = id WHERE update_id IS NULL")


def downgrade() -> None:
    op.drop_index(op.f('ix_events_update_id'), table_name='events')
    op.drop_column('events', 'update_id')
