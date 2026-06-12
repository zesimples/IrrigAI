"""Set you@irrigai.dev to admin role."""
import asyncio
from sqlalchemy import update
from app.database import AsyncSessionLocal
from app.models.user import User


async def main():
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(User).where(User.email == "you@irrigai.dev").values(role="admin")
        )
        await db.commit()
        print(f"Updated {result.rowcount} user(s) to admin role.")


asyncio.run(main())
