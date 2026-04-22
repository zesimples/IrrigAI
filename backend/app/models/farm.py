from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class Farm(Base, TimestampMixin):
    __tablename__ = "farm"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True, comment="metres above sea level for ET0 correction")
    region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Europe/Lisbon")
    owner_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("user.id"), nullable=False)

    # Per-farm MyIrrigation API credentials (override global .env values when set)
    myirrigation_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    myirrigation_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    myirrigation_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    myirrigation_client_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    myirrigation_weather_device_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="farms")  # noqa: F821
    plots: Mapped[list["Plot"]] = relationship("Plot", back_populates="farm", cascade="all, delete-orphan")  # noqa: F821
    weather_observations: Mapped[list["WeatherObservation"]] = relationship(  # noqa: F821
        "WeatherObservation", back_populates="farm", cascade="all, delete-orphan"
    )
    weather_forecasts: Mapped[list["WeatherForecast"]] = relationship(  # noqa: F821
        "WeatherForecast", back_populates="farm", cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(  # noqa: F821
        "Alert", back_populates="farm", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Farm '{self.name}'>"
