"""add calibration history and recommendation outcomes

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "n4o5p6q7r8s9"
down_revision: Union[str, None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "probe_calibration_run",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("sector_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("observed_fc", sa.Float(), nullable=False),
        sa.Column("observed_refill", sa.Float(), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("num_cycles", sa.Integer(), nullable=False),
        sa.Column("consistency", sa.Float(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("previous_fc", sa.Float(), nullable=True),
        sa.Column("previous_refill", sa.Float(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sector_id"], ["sector.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_probe_calibration_run_sector_time",
        "probe_calibration_run",
        ["sector_id", "computed_at"],
        unique=False,
    )
    # Preserve the currently active calibration as the first immutable history row.
    op.execute(
        """
        INSERT INTO probe_calibration_run (
          id, sector_id, observed_fc, observed_refill, method, num_cycles,
          consistency, window_days, computed_at, source, status, applied_at,
          created_at, updated_at
        )
        SELECT gen_random_uuid(), sector_id, observed_fc, observed_refill, method,
          num_cycles, consistency, window_days, computed_at, 'migration', 'applied',
          computed_at, created_at, updated_at
        FROM probe_calibration
        """
    )

    op.create_table(
        "recommendation_outcome",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("sector_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("irrigation_event_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("detected_event_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("recommended_depth_mm", sa.Float(), nullable=True),
        sa.Column("actual_applied_mm", sa.Float(), nullable=True),
        sa.Column("dose_error_mm", sa.Float(), nullable=True),
        sa.Column("dose_error_pct", sa.Float(), nullable=True),
        sa.Column("pre_irrigation_vwc", sa.Float(), nullable=True),
        sa.Column("post_irrigation_vwc", sa.Float(), nullable=True),
        sa.Column("probe_response_delta", sa.Float(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["detected_event_id"], ["irrigation_event_detected.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["irrigation_event_id"], ["irrigation_event.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recommendation_id"], ["recommendation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sector_id"], ["sector.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recommendation_id", name="uq_recommendation_outcome_recommendation"),
    )
    op.create_index(
        "ix_recommendation_outcome_sector_time",
        "recommendation_outcome",
        ["sector_id", "evaluated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_recommendation_outcome_sector_time", table_name="recommendation_outcome")
    op.drop_table("recommendation_outcome")
    op.drop_index("ix_probe_calibration_run_sector_time", table_name="probe_calibration_run")
    op.drop_table("probe_calibration_run")
