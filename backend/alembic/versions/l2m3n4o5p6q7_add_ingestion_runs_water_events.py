"""Add provider_ingestion_run, per-depth freshness fields and detected_water_event

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-05-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── provider_ingestion_run ────────────────────────────────────────────────
    op.create_table(
        "provider_ingestion_run",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("farm.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "probe_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("probe.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("probe_external_id", sa.String(255), nullable=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("requested_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_first_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_last_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_records_seen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("provider_records_parsed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_null", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_sentinel", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_unknown_depth", sa.Integer, nullable=False, server_default="0"),
        sa.Column("skipped_duplicate", sa.Integer, nullable=False, server_default="0"),
        sa.Column("inserted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flagged_invalid", sa.Integer, nullable=False, server_default="0"),
        sa.Column("flagged_suspect", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_provider_ingestion_run_farm_id", "provider_ingestion_run", ["farm_id"])
    op.create_index("ix_provider_ingestion_run_probe_id", "provider_ingestion_run", ["probe_id"])
    op.create_index("ix_provider_ingestion_run_provider", "provider_ingestion_run", ["provider"])
    op.create_index(
        "ix_provider_ingestion_run_started_at", "provider_ingestion_run", ["started_at"]
    )

    # ── probe_depth: freshness columns ────────────────────────────────────────
    op.add_column("probe_depth", sa.Column("last_reading_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("probe_depth", sa.Column("last_quality_flag", sa.String(20), nullable=True))
    op.add_column("probe_depth", sa.Column("last_unit", sa.String(20), nullable=True))
    op.add_column(
        "probe_depth",
        sa.Column("readings_count_total", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column("probe_depth", sa.Column("last_gap_detected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "probe_depth",
        sa.Column("data_status", sa.String(20), nullable=False, server_default="unknown"),
    )

    # ── detected_water_event ──────────────────────────────────────────────────
    op.create_table(
        "detected_water_event",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "probe_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("probe.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sector_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("sector.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "farm_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("farm.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("confidence", sa.String(20), nullable=False),
        sa.Column("score", sa.Float, nullable=False, server_default="0"),
        sa.Column("probability_irrigation", sa.Float, nullable=False, server_default="0"),
        sa.Column("probability_rain", sa.Float, nullable=False, server_default="0"),
        sa.Column("probability_unlogged", sa.Float, nullable=False, server_default="0"),
        sa.Column("source_match_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("depth_sequence_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("signal_strength_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("sensor_quality_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("depths_cm", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("delta_vwc", sa.Float, nullable=False, server_default="0"),
        sa.Column("rainfall_mm", sa.Float, nullable=True),
        sa.Column("irrigation_mm", sa.Float, nullable=True),
        sa.Column(
            "matched_irrigation_event_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("irrigation_event.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "matched_weather_observation_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("weather_observation.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "confirmed_by",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("message", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_detected_water_event_probe_id", "detected_water_event", ["probe_id"])
    op.create_index("ix_detected_water_event_sector_id", "detected_water_event", ["sector_id"])
    op.create_index("ix_detected_water_event_farm_id", "detected_water_event", ["farm_id"])
    op.create_index("ix_detected_water_event_timestamp", "detected_water_event", ["timestamp"])
    op.create_unique_constraint(
        "uq_detected_water_event", "detected_water_event", ["probe_id", "timestamp", "kind"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_detected_water_event", "detected_water_event", type_="unique")
    op.drop_index("ix_detected_water_event_timestamp", table_name="detected_water_event")
    op.drop_index("ix_detected_water_event_farm_id", table_name="detected_water_event")
    op.drop_index("ix_detected_water_event_sector_id", table_name="detected_water_event")
    op.drop_index("ix_detected_water_event_probe_id", table_name="detected_water_event")
    op.drop_table("detected_water_event")

    op.drop_column("probe_depth", "data_status")
    op.drop_column("probe_depth", "last_gap_detected_at")
    op.drop_column("probe_depth", "readings_count_total")
    op.drop_column("probe_depth", "last_unit")
    op.drop_column("probe_depth", "last_quality_flag")
    op.drop_column("probe_depth", "last_reading_at")

    op.drop_index("ix_provider_ingestion_run_started_at", table_name="provider_ingestion_run")
    op.drop_index("ix_provider_ingestion_run_provider", table_name="provider_ingestion_run")
    op.drop_index("ix_provider_ingestion_run_probe_id", table_name="provider_ingestion_run")
    op.drop_index("ix_provider_ingestion_run_farm_id", table_name="provider_ingestion_run")
    op.drop_table("provider_ingestion_run")
