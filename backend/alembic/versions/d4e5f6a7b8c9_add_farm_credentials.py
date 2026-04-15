"""add per-farm MyIrrigation credentials to farm table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('farm', sa.Column('myirrigation_username', sa.String(255), nullable=True))
    op.add_column('farm', sa.Column('myirrigation_password', sa.String(255), nullable=True))
    op.add_column('farm', sa.Column('myirrigation_client_id', sa.String(255), nullable=True))
    op.add_column('farm', sa.Column('myirrigation_client_secret', sa.String(255), nullable=True))
    op.add_column('farm', sa.Column('myirrigation_weather_device_id', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('farm', 'myirrigation_weather_device_id')
    op.drop_column('farm', 'myirrigation_client_secret')
    op.drop_column('farm', 'myirrigation_client_id')
    op.drop_column('farm', 'myirrigation_password')
    op.drop_column('farm', 'myirrigation_username')
