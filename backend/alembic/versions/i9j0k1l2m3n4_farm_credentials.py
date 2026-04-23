"""Move MyIrrigation credentials from farm to encrypted farm_credentials table

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-04-23

Data migration: existing plaintext credentials are encrypted with ENCRYPTION_KEY
(or SECRET_KEY if ENCRYPTION_KEY is not set) and copied to the new table.
The old columns are then dropped from farm.
"""
import base64
import hashlib
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import UUID

revision = "i9j0k1l2m3n4"
down_revision = "h8i9j0k1l2m3"
branch_labels = None
depends_on = None


def _make_fernet():
    from cryptography.fernet import Fernet
    key_material = os.environ.get("ENCRYPTION_KEY") or os.environ.get("SECRET_KEY", "change-me-in-production")
    digest = hashlib.sha256(key_material.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _enc(fernet, value: str | None) -> str | None:
    if value is None:
        return None
    return fernet.encrypt(value.encode()).decode()


def upgrade() -> None:
    op.create_table(
        "farm_credentials",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("farm_id", UUID(as_uuid=False), sa.ForeignKey("farm.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("username_enc", sa.Text, nullable=True),
        sa.Column("password_enc", sa.Text, nullable=True),
        sa.Column("client_id_enc", sa.Text, nullable=True),
        sa.Column("client_secret_enc", sa.Text, nullable=True),
        sa.Column("weather_device_id", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Migrate existing plaintext credentials → encrypted rows
    conn = op.get_bind()
    fernet = _make_fernet()
    import uuid

    rows = conn.execute(text(
        "SELECT id, myirrigation_username, myirrigation_password, "
        "myirrigation_client_id, myirrigation_client_secret, "
        "myirrigation_weather_device_id FROM farm"
    )).fetchall()

    for row in rows:
        farm_id, uname, pwd, cid, csec, device = (
            row[0], row[1], row[2], row[3], row[4], row[5]
        )
        if any([uname, pwd, cid, csec, device]):
            conn.execute(text(
                "INSERT INTO farm_credentials "
                "(id, farm_id, username_enc, password_enc, client_id_enc, client_secret_enc, weather_device_id, created_at, updated_at) "
                "VALUES (:id, :farm_id, :username_enc, :password_enc, :client_id_enc, :client_secret_enc, :device_id, NOW(), NOW())"
            ), {
                "id": str(uuid.uuid4()),
                "farm_id": farm_id,
                "username_enc": _enc(fernet, uname),
                "password_enc": _enc(fernet, pwd),
                "client_id_enc": _enc(fernet, cid),
                "client_secret_enc": _enc(fernet, csec),
                "device_id": device,
            })

    op.drop_column("farm", "myirrigation_username")
    op.drop_column("farm", "myirrigation_password")
    op.drop_column("farm", "myirrigation_client_id")
    op.drop_column("farm", "myirrigation_client_secret")
    op.drop_column("farm", "myirrigation_weather_device_id")


def downgrade() -> None:
    op.add_column("farm", sa.Column("myirrigation_username", sa.String(255), nullable=True))
    op.add_column("farm", sa.Column("myirrigation_password", sa.String(255), nullable=True))
    op.add_column("farm", sa.Column("myirrigation_client_id", sa.String(255), nullable=True))
    op.add_column("farm", sa.Column("myirrigation_client_secret", sa.String(255), nullable=True))
    op.add_column("farm", sa.Column("myirrigation_weather_device_id", sa.String(50), nullable=True))
    # NOTE: downgrade does not decrypt — credentials are lost on rollback
    op.drop_table("farm_credentials")
