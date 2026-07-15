"""add alert reconciliation sources and rule keys

Revision ID: m3n4o5p6q7r8
Revises: 09ceb934819b
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, None] = "09ceb934819b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "alert",
        sa.Column("source", sa.String(length=50), server_default="core", nullable=False),
    )
    op.add_column("alert", sa.Column("rule_key", sa.String(length=255), nullable=True))
    op.execute(
        """
        UPDATE alert SET source = CASE
          WHEN alert_type IN ('flowmeter_flow_rate_high', 'flowmeter_flow_rate_low',
                              'flowmeter_mid_event_zeros') THEN 'flowmeter_flow_rate'
          WHEN alert_type IN ('flowmeter_deviation', 'flowmeter_insufficient_data')
            THEN 'flowmeter_deviation'
          WHEN alert_type IN ('probe_anomaly', 'underperformance')
               OR data ? 'anomaly_type' THEN 'anomaly'
          ELSE 'core'
        END
        """
    )
    op.execute(
        """
        UPDATE alert
        SET rule_key = alert_type || ':' || COALESCE(sector_id::text, farm_id::text)
        WHERE rule_key IS NULL
        """
    )
    op.create_index("ix_alert_source", "alert", ["source"], unique=False)
    op.create_index("ix_alert_rule_key", "alert", ["rule_key"], unique=False)
    op.create_index(
        "ix_alert_reconciliation",
        "alert",
        ["farm_id", "source", "rule_key", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_alert_reconciliation", table_name="alert")
    op.drop_index("ix_alert_rule_key", table_name="alert")
    op.drop_index("ix_alert_source", table_name="alert")
    op.drop_column("alert", "rule_key")
    op.drop_column("alert", "source")
