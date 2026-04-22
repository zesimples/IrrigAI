"""add farm elevation_m column

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-04-22
"""
from alembic import op
import sqlalchemy as sa

revision = "h8i9j0k1l2m3"
down_revision = "g7h8i9j0k1l2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "farm",
        sa.Column(
            "elevation_m",
            sa.Float(),
            nullable=True,
            comment="metres above sea level for ET0 correction",
        ),
    )


def downgrade() -> None:
    op.drop_column("farm", "elevation_m")
