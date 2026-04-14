"""add sector_override table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sector_override',
        sa.Column('id', UUID(as_uuid=False), primary_key=True),
        sa.Column('sector_id', UUID(as_uuid=False), sa.ForeignKey('sector.id'), nullable=False, index=True),
        sa.Column('override_type', sa.String(50), nullable=False),
        sa.Column('value', sa.Float(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('created_by_id', UUID(as_uuid=False), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('valid_until', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('override_strategy', sa.String(50), nullable=False, server_default='one_time'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_sector_override_sector_id', 'sector_override', ['sector_id'])


def downgrade() -> None:
    op.drop_index('ix_sector_override_sector_id', table_name='sector_override')
    op.drop_table('sector_override')
