"""Audit log service — persists all significant state changes."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

# Canonical action names
RECOMMENDATION_GENERATED = "recommendation_generated"
RECOMMENDATION_ACCEPTED = "recommendation_accepted"
RECOMMENDATION_REJECTED = "recommendation_rejected"
RECOMMENDATION_OVERRIDDEN = "recommendation_overridden"
IRRIGATION_LOGGED = "irrigation_logged"
SECTOR_UPDATED = "sector_updated"
ALERT_ACKNOWLEDGED = "alert_acknowledged"
ALERT_RESOLVED = "alert_resolved"
OVERRIDE_CREATED = "override_created"
OVERRIDE_REMOVED = "override_removed"
DATA_INGESTED = "data_ingested"


class AuditService:
    async def log(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        db: AsyncSession,
        user_id: str | None = None,
        before_data: dict | None = None,
        after_data: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        """Create an audit log entry. Never raises — failures are logged only."""
        try:
            entry = AuditLog(
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                user_id=user_id,
                before_data=before_data,
                after_data=after_data,
                ip_address=ip_address,
            )
            db.add(entry)
            await db.flush()
            logger.debug("Audit: %s %s/%s by user=%s", action, entity_type, entity_id, user_id)
        except Exception:
            logger.exception("Failed to write audit log: %s %s/%s", action, entity_type, entity_id)


# Module-level singleton
audit = AuditService()
