"""add remote_id column

Revision ID: 8a72d18ff538
Revises: 0001
Create Date: 2026-07-07 07:49:15.559146

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '8a72d18ff538'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('remote_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(op.f('ix_events_remote_id'), 'events', ['remote_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_events_remote_id'), table_name='events')
    op.drop_column('events', 'remote_id')
