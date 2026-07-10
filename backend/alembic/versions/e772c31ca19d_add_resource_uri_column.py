"""add_resource_uri_column

Revision ID: e772c31ca19d
Revises: 80580b8a7125
Create Date: 2026-07-10 10:12:18.188285

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e772c31ca19d'
down_revision: Union[str, None] = '80580b8a7125'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('resource_uri', sa.String(), nullable=True))
    op.create_index(op.f('ix_events_resource_uri'), 'events', ['resource_uri'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_events_resource_uri'), table_name='events')
    op.drop_column('events', 'resource_uri')
