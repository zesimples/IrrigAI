"""add soil overrides to sector_crop_profile

Revision ID: a1b2c3d4e5f6
Revises: 624229864a91
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '624229864a91'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sector_crop_profile', sa.Column('field_capacity', sa.Float(), nullable=True))
    op.add_column('sector_crop_profile', sa.Column('wilting_point', sa.Float(), nullable=True))
    op.add_column('sector_crop_profile', sa.Column('soil_preset_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('sector_crop_profile', 'soil_preset_id')
    op.drop_column('sector_crop_profile', 'wilting_point')
    op.drop_column('sector_crop_profile', 'field_capacity')
