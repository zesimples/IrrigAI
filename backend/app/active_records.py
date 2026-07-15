"""Canonical queries for records that may participate in live operations.

Archived farms, plots, and sectors remain addressable for restore/history APIs,
but must never be ingested, analysed, alerted on, or included in current-state
dashboards.  Keeping these predicates here prevents background jobs from slowly
diverging as new traversals are added.
"""

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Farm, Plot, Sector


def active_farms_stmt() -> Select:
    return select(Farm).where(Farm.is_archived.is_(False))


def active_plots_stmt(farm_id: str) -> Select:
    return select(Plot).where(
        Plot.farm_id == farm_id,
        Plot.is_archived.is_(False),
    )


def active_sectors_stmt(plot_id: str) -> Select:
    return select(Sector).where(
        Sector.plot_id == plot_id,
        Sector.is_archived.is_(False),
    )


async def get_active_farm(db: AsyncSession, farm_id: str) -> Farm | None:
    return (
        await db.execute(active_farms_stmt().where(Farm.id == farm_id))
    ).scalar_one_or_none()


async def get_active_sector(db: AsyncSession, sector_id: str) -> Sector | None:
    """Return a sector only when its complete ownership chain is active."""
    return (
        await db.execute(
            select(Sector)
            .join(Plot, Sector.plot_id == Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(
                Sector.id == sector_id,
                Sector.is_archived.is_(False),
                Plot.is_archived.is_(False),
                Farm.is_archived.is_(False),
            )
        )
    ).scalar_one_or_none()
