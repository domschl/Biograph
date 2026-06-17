"""Initial schema: create events table.

Revision ID: 0001
Revises:
Create Date: 2026-06-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("ev_type", sa.String(length=64), nullable=False),
        sa.Column("source_host", sa.String(), nullable=True),
        sa.Column("source_app", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("tags", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_timestamp", "events", ["timestamp"])
    op.create_index("ix_events_received_at", "events", ["received_at"])
    op.create_index("ix_events_ev_type", "events", ["ev_type"])
    op.create_index("ix_events_source_host", "events", ["source_host"])
    op.create_index("ix_events_source_app", "events", ["source_app"])


def downgrade() -> None:
    op.drop_index("ix_events_source_app", table_name="events")
    op.drop_index("ix_events_source_host", table_name="events")
    op.drop_index("ix_events_ev_type", table_name="events")
    op.drop_index("ix_events_received_at", table_name="events")
    op.drop_index("ix_events_timestamp", table_name="events")
    op.drop_table("events")
