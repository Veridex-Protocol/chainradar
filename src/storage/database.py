"""Database session and engine management supporting PostgreSQL and SQLite."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from src.config import settings
from src.storage.models import Base


def _custom_json_serializer(obj):
    return json.dumps(obj, default=str)


class DatabaseManager:
    """Manages async database engine and sessions."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.engine: AsyncEngine = self._create_engine(db_url)
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    def _create_engine(self, url: str) -> AsyncEngine:
        if url.startswith("sqlite"):
            db_path_str = url.replace("sqlite+aiosqlite:///", "")
            if db_path_str and not db_path_str.startswith(":memory:"):
                db_path = Path(db_path_str).resolve()
                db_path.parent.mkdir(parents=True, exist_ok=True)
            return create_async_engine(
                url,
                echo=settings.ENVIRONMENT == "debug",
                json_serializer=_custom_json_serializer,
            )
        else:
            return create_async_engine(
                url,
                pool_size=10,
                max_overflow=20,
                echo=settings.ENVIRONMENT == "debug",
                json_serializer=_custom_json_serializer,
            )

    async def init_db(self) -> None:
        """Create all tables if they do not exist."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager for an async database session with automatic commit/rollback."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


db_manager = DatabaseManager(settings.DATABASE_URL)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for DB sessions."""
    async with db_manager.session() as session:
        yield session
