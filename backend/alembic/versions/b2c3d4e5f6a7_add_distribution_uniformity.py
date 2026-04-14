"""add distribution_uniformity to irrigation_system

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'irrigation_system',
        sa.Column(
            'distribution_uniformity',
            sa.Float(),
            nullable=False,
            server_default='0.90',
            comment='Fraction 0–1; how evenly water is distributed across the field',
        ),
    )


def downgrade() -> None:
    op.drop_column('irrigation_system', 'distribution_uniformity')
