from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class WeatherForecast(Base, TimestampMixin):
    __tablename__ = "weather_forecast"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    farm_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("farm.id"), nullable=False, index=True)
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    temperature_max_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    rainfall_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    rainfall_probability_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    et0_mm: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    farm: Mapped["Farm"] = relationship("Farm", back_populates="weather_forecasts")  # noqa: F821

    def __repr__(self) -> str:
        return f"<WeatherForecast farm={self.farm_id} date={self.forecast_date}>"
