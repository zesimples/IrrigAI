"""add performance indexes for frequent query patterns

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-22
"""
from alembic import op

revision = 'g7h8i9j0k1l2'
down_revision = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # recommendation.generated_at — ORDER BY generated_at DESC LIMIT 1 on every sector status load
    op.create_index(
        "ix_recommendation_generated_at",
        "recommendation",
        ["generated_at"],
    )

    # (sector_id, start_time) — latest irrigation event per sector
    op.create_index(
        "ix_irrigation_event_sector_start",
        "irrigation_event",
        ["sector_id", "start_time"],
    )

    # alert.is_active — WHERE is_active = TRUE filtered on every sector status
    op.create_index(
        "ix_alert_is_active",
        "alert",
        ["is_active"],
    )

    # (farm_id, timestamp) composite — weather range queries per farm
    op.create_index(
        "ix_weather_obs_farm_timestamp",
        "weather_observation",
        ["farm_id", "timestamp"],
    )

    # (farm_id, date) composite on weather_forecast
    op.create_index(
        "ix_weather_forecast_farm_date",
        "weather_forecast",
        ["farm_id", "date"],
    )


def downgrade() -> None:
    op.drop_index("ix_weather_forecast_farm_date", table_name="weather_forecast")
    op.drop_index("ix_weather_obs_farm_timestamp", table_name="weather_observation")
    op.drop_index("ix_alert_is_active", table_name="alert")
    op.drop_index("ix_irrigation_event_sector_start", table_name="irrigation_event")
    op.drop_index("ix_recommendation_generated_at", table_name="recommendation")
