"""Create a dedicated login user for Herdade dos Conqueiros and reassign the farm.

Run inside the backend container:
    python scripts/create_conqueiros_user.py

The script is idempotent — safe to run again if the user already exists.

After running:
  - New user can log in at the IrrigAI frontend with these credentials:
      email:    conqueiros@irrigai.pt
      password: (printed below — override with --password)
  - The Conqueiros farm ownership is transferred to the new user.
  - Admin users (role=admin) retain visibility over all farms via the API.
"""
import argparse
import asyncio
import secrets
import string

from sqlalchemy import select

from app.auth import hash_password
from app.database import AsyncSessionLocal
from app.models.base import new_uuid
from app.models.farm import Farm
from app.models.user import User

DEFAULT_EMAIL = "conqueiros@irrigai.pt"
DEFAULT_NAME = "Herdade dos Conqueiros"
FARM_NAME = "Herdade dos Conqueiros"


def _random_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def main(email: str, password: str | None) -> None:
    async with AsyncSessionLocal() as db:
        # 1. Find the Conqueiros farm
        farm = (
            await db.execute(select(Farm).where(Farm.name == FARM_NAME))
        ).scalar_one_or_none()
        if farm is None:
            print(f"[ERROR] Farm '{FARM_NAME}' not found. Run the seed script first.")
            return

        # 2. Upsert the user
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        plain_password = password or _random_password()

        if user is None:
            user = User(
                id=new_uuid(),
                email=email,
                name=DEFAULT_NAME,
                role="grower",
                language="pt",
                is_active=True,
                hashed_password=hash_password(plain_password),
            )
            db.add(user)
            await db.flush()
            print(f"[+] Created user: {email}")
        else:
            user.hashed_password = hash_password(plain_password)
            print(f"[~] User already exists — password reset: {email}")

        # 3. Reassign farm ownership
        old_owner = farm.owner_id
        farm.owner_id = user.id
        await db.commit()

        if old_owner != user.id:
            print(f"[+] Farm '{FARM_NAME}' reassigned from {old_owner} → {user.id}")
        else:
            print(f"[=] Farm '{FARM_NAME}' already owned by this user")

        print()
        print("=== Conqueiros login credentials ===")
        print(f"  Email:    {email}")
        print(f"  Password: {plain_password}")
        print()
        print("Admin users (role=admin) can still see all farms via the API.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create Conqueiros user and reassign farm")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="Login email for the new user")
    parser.add_argument("--password", default=None, help="Password (auto-generated if omitted)")
    args = parser.parse_args()

    asyncio.run(main(args.email, args.password))
