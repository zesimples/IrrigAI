"""Add soft deletion (is_archived, archived_at) to farm, plot, sector

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-04-23
"""

import sqlalchemy as sa
from alembic import op

revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("farm", "plot", "sector"):
        op.add_column(table, sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"))
        op.add_column(table, sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for table in ("farm", "plot", "sector"):
        op.drop_column(table, "archived_at")
        op.drop_column(table, "is_archived")
