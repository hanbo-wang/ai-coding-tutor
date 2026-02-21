"""Database initialisation and migration runner."""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.config import settings
from app.db.session import AsyncSessionLocal
from app.models.user import User

def _build_alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


async def init_db() -> None:
    """Run Alembic migrations to keep the schema up to date."""
    cfg = _build_alembic_config()
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await _ensure_admin_user()


async def _ensure_admin_user() -> None:
    """Promote configured admin accounts when they exist."""
    admin_emails = settings.admin_email_set
    if not admin_emails:
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email.in_(admin_emails)))
        users = result.scalars().all()

        changed = False
        for user in users:
            if user.is_admin:
                continue
            user.is_admin = True
            changed = True

        if not changed:
            return
        await session.commit()
