"""Ensure an admin@pae.dev user exists (for local dev / Playwright tests).

Idempotent. Run via:
    docker compose exec backend uv run python -m app.scripts.ensure_admin
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.hashing import hash_password
from app.models.user import User

EMAIL = "admin@pae.dev"
PASSWORD = "admin-password-123"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(User).where(User.email == EMAIL))
        ).scalar_one_or_none()
        if row is None:
            row = User(
                email=EMAIL,
                full_name="Admin Tester",
                hashed_password=hash_password(PASSWORD),
                role="admin",
                is_verified=True,
                is_active=True,
            )
            db.add(row)
            await db.flush()
            print("created admin", row.id)
        else:
            row.role = "admin"
            row.is_verified = True
            row.is_active = True
            row.hashed_password = hash_password(PASSWORD)
            print("updated admin", row.id)
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
