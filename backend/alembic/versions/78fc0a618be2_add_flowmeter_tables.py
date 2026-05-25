"""add flowmeter tables

Revision ID: 78fc0a618be2
Revises: l2m3n4o5p6q7
Create Date: 2026-05-22 11:38:54.744596

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '78fc0a618be2'
down_revision: Union[str, None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- flowmeter device table --
    op.create_table(
        'flowmeter',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('sector_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('external_device_id', sa.Integer(), nullable=False),
        sa.Column('serial_number', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_reading_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['sector_id'], ['sector.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_flowmeter_sector_id'), 'flowmeter', ['sector_id'], unique=True)
    op.create_index(op.f('ix_flowmeter_external_device_id'), 'flowmeter', ['external_device_id'], unique=False)

    # -- readings time-series table --
    op.create_table(
        'flowmeter_reading',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('flowmeter_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('value_m3_ha', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['flowmeter_id'], ['flowmeter.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('flowmeter_id', 'timestamp', name='uq_flowmeter_reading_device_ts'),
    )
    # Composite index for the most common query: readings for a flowmeter in a time window
    op.create_index('ix_flowmeter_reading_fm_ts', 'flowmeter_reading', ['flowmeter_id', 'timestamp'], unique=False)

    # Convert to TimescaleDB hypertable (same pattern as probe_reading migration)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                ALTER TABLE flowmeter_reading DROP CONSTRAINT flowmeter_reading_pkey;
                ALTER TABLE flowmeter_reading ADD PRIMARY KEY (id, timestamp);
                PERFORM create_hypertable(
                    'flowmeter_reading', 'timestamp',
                    if_not_exists => TRUE,
                    migrate_data => TRUE
                );
            END IF;
        END $$;
    """)

    # -- detected irrigation events table --
    op.create_table(
        'irrigation_event_detected',
        sa.Column('id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('flowmeter_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('sector_id', sa.UUID(as_uuid=False), nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Float(), nullable=False),
        sa.Column('total_m3_ha', sa.Float(), nullable=False),
        sa.Column('peak_m3_ha', sa.Float(), nullable=False),
        sa.Column('num_readings', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['flowmeter_id'], ['flowmeter.id']),
        sa.ForeignKeyConstraint(['sector_id'], ['sector.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('flowmeter_id', 'start_time', name='uq_irrigation_event_detected_device_start'),
    )
    op.create_index(op.f('ix_irrigation_event_detected_date'), 'irrigation_event_detected', ['date'], unique=False)
    # Composite indexes for common query patterns
    op.create_index('ix_irrigation_event_detected_fm_start', 'irrigation_event_detected', ['flowmeter_id', 'start_time'], unique=False)
    op.create_index('ix_irrigation_event_detected_sector_start', 'irrigation_event_detected', ['sector_id', 'start_time'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_irrigation_event_detected_sector_start', table_name='irrigation_event_detected')
    op.drop_index('ix_irrigation_event_detected_fm_start', table_name='irrigation_event_detected')
    op.drop_index(op.f('ix_irrigation_event_detected_date'), table_name='irrigation_event_detected')
    op.drop_table('irrigation_event_detected')

    op.drop_index('ix_flowmeter_reading_fm_ts', table_name='flowmeter_reading')
    op.drop_table('flowmeter_reading')

    op.drop_index(op.f('ix_flowmeter_external_device_id'), table_name='flowmeter')
    op.drop_index(op.f('ix_flowmeter_sector_id'), table_name='flowmeter')
    op.drop_table('flowmeter')
