from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import UserRole
from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class User(Base, TimestampMixin):
    __tablename__ = "user"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(50), nullable=False, default=UserRole.GROWER)
    language: Mapped[str] = mapped_column(String(5), nullable=False, default="pt")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationships
    farms: Mapped[list["Farm"]] = relationship("Farm", back_populates="owner")  # noqa: F821
    accepted_recommendations: Mapped[list["Recommendation"]] = relationship(  # noqa: F821
        "Recommendation", back_populates="accepted_by"
    )
    acknowledged_alerts: Mapped[list["Alert"]] = relationship(  # noqa: F821
        "Alert", back_populates="acknowledged_by"
    )

    def __repr__(self) -> str:
        return f"<User {self.email} [{self.role}]>"
