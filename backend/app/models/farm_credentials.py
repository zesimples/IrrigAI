from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.crypto import EncryptedString
from app.database import Base
from app.models.base import TimestampMixin, new_uuid


class FarmCredentials(Base, TimestampMixin):
    """Per-farm MyIrrigation API credentials, encrypted at rest.

    Kept in a separate table so SELECT * FROM farm never returns raw secrets.
    Only loaded when explicitly requested via selectinload(Farm.credentials).
    """
    __tablename__ = "farm_credentials"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    farm_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("farm.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # Encrypted columns — Python attributes expose plaintext; DB stores ciphertext.
    username: Mapped[str | None] = mapped_column("username_enc", EncryptedString, nullable=True)
    password: Mapped[str | None] = mapped_column("password_enc", EncryptedString, nullable=True)
    client_id: Mapped[str | None] = mapped_column("client_id_enc", EncryptedString, nullable=True)
    client_secret: Mapped[str | None] = mapped_column("client_secret_enc", EncryptedString, nullable=True)
    weather_device_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    farm: Mapped["Farm"] = relationship("Farm", back_populates="credentials")  # noqa: F821

    def __repr__(self) -> str:
        return f"<FarmCredentials farm_id='{self.farm_id}'>"
