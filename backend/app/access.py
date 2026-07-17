from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.enums import UserRole
from app.database import get_db
from app.models import (
    Alert,
    DetectedWaterEvent,
    Farm,
    IrrigationEvent,
    Plot,
    Probe,
    Recommendation,
    Sector,
    SectorOverride,
    User,
)

CurrentUser = Annotated[User, Depends(get_current_user)]
DBSession = Annotated[AsyncSession, Depends(get_db)]


class AccessController:
    def __init__(self, db: AsyncSession, current_user: User) -> None:
        self.db = db
        self.current_user = current_user

    @property
    def is_admin(self) -> bool:
        return self.current_user.role == UserRole.ADMIN or self.current_user.role == "admin"

    def _not_found(self, resource: str) -> None:
        raise HTTPException(404, detail=f"{resource} not found")

    def _owned_filter(self):
        if self.is_admin:
            return true()
        return Farm.owner_id == self.current_user.id

    async def require_admin(self) -> None:
        if not self.is_admin:
            raise HTTPException(404, detail="Not found")

    async def farm(self, farm_id: str) -> Farm:
        stmt = select(Farm).where(Farm.id == farm_id)
        if not self.is_admin:
            stmt = stmt.where(Farm.owner_id == self.current_user.id)
        farm = (await self.db.execute(stmt)).scalar_one_or_none()
        if farm is None:
            self._not_found("Farm")
        return farm

    async def plot(self, plot_id: str) -> Plot:
        stmt = select(Plot).join(Farm, Plot.farm_id == Farm.id).where(
            Plot.id == plot_id,
            self._owned_filter(),
        )
        plot = (await self.db.execute(stmt)).scalar_one_or_none()
        if plot is None:
            self._not_found("Plot")
        return plot

    async def sector(self, sector_id: str) -> Sector:
        stmt = (
            select(Sector)
            .join(Plot, Sector.plot_id == Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(Sector.id == sector_id, self._owned_filter())
        )
        sector = (await self.db.execute(stmt)).scalar_one_or_none()
        if sector is None:
            self._not_found("Sector")
        return sector

    async def sector_in_farm(self, sector_id: str, farm_id: str) -> Sector:
        """Resolve an owned sector while locking it to the requested farm scope."""
        stmt = (
            select(Sector)
            .join(Plot, Sector.plot_id == Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(
                Sector.id == sector_id,
                Plot.farm_id == farm_id,
                self._owned_filter(),
            )
        )
        sector = (await self.db.execute(stmt)).scalar_one_or_none()
        if sector is None:
            self._not_found("Sector")
        return sector

    async def probe(self, probe_id: str) -> Probe:
        stmt = (
            select(Probe)
            .join(Sector, Probe.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(Probe.id == probe_id, self._owned_filter())
        )
        probe = (await self.db.execute(stmt)).scalar_one_or_none()
        if probe is None:
            self._not_found("Probe")
        return probe

    async def recommendation(self, rec_id: str) -> Recommendation:
        stmt = (
            select(Recommendation)
            .join(Sector, Recommendation.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(Recommendation.id == rec_id, self._owned_filter())
        )
        recommendation = (await self.db.execute(stmt)).scalar_one_or_none()
        if recommendation is None:
            self._not_found("Recommendation")
        return recommendation

    async def irrigation_event(self, event_id: str) -> IrrigationEvent:
        stmt = (
            select(IrrigationEvent)
            .join(Sector, IrrigationEvent.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(IrrigationEvent.id == event_id, self._owned_filter())
        )
        event = (await self.db.execute(stmt)).scalar_one_or_none()
        if event is None:
            self._not_found("Irrigation event")
        return event

    async def alert(self, alert_id: str) -> Alert:
        stmt = select(Alert).join(Farm, Alert.farm_id == Farm.id).where(
            Alert.id == alert_id,
            self._owned_filter(),
        )
        alert = (await self.db.execute(stmt)).scalar_one_or_none()
        if alert is None:
            self._not_found("Alert")
        return alert

    async def override(self, override_id: str) -> SectorOverride:
        stmt = (
            select(SectorOverride)
            .join(Sector, SectorOverride.sector_id == Sector.id)
            .join(Plot, Sector.plot_id == Plot.id)
            .join(Farm, Plot.farm_id == Farm.id)
            .where(SectorOverride.id == override_id, self._owned_filter())
        )
        override = (await self.db.execute(stmt)).scalar_one_or_none()
        if override is None:
            self._not_found("Override")
        return override

    async def water_event(self, event_id: str) -> DetectedWaterEvent:
        stmt = select(DetectedWaterEvent).outerjoin(
            Farm, DetectedWaterEvent.farm_id == Farm.id
        ).where(DetectedWaterEvent.id == event_id)
        if not self.is_admin:
            stmt = stmt.where(Farm.owner_id == self.current_user.id)
        event = (await self.db.execute(stmt)).scalar_one_or_none()
        if event is None:
            self._not_found("Water event")
        return event


def get_access_controller(
    current_user: CurrentUser,
    db: DBSession,
) -> AccessController:
    return AccessController(db, current_user)


Access = Annotated[AccessController, Depends(get_access_controller)]
