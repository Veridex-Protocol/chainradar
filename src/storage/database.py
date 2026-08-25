"""Database session and engine management supporting PostgreSQL and SQLite."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Awaitable, Callable
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from src.config import settings
from src.storage.models import Base

logger = logging.getLogger(__name__)

# PostgreSQL aborts one side of a lock conflict rather than hanging. These are
# recoverable by retrying the transaction, not bugs to surface to a user.
_TRANSIENT_DB_ERRORS = {
    "DeadlockDetectedError",
    "SerializationError",
    "LockNotAvailableError",
    "TooManyConnectionsError",
    "CannotConnectNowError",
}


def is_transient_db_error(exc: BaseException) -> bool:
    """True when a database error is worth retrying rather than reporting."""
    seen = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ in _TRANSIENT_DB_ERRORS:
            return True
        # SQLAlchemy wraps the driver exception on `.orig`.
        current = getattr(current, "orig", None) or current.__cause__
    return False


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

    async def verify_schema_is_current(self) -> None:
        """Fail fast when the database is not migrated to head.

        Creating tables at startup would let a running instance drift from the
        migration history; refusing to start makes a missed `alembic upgrade`
        obvious instead of producing confusing runtime errors later.
        """
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import text as sql_text

        repo_root = Path(__file__).resolve().parents[2]
        cfg = Config(str(repo_root / "alembic.ini"))
        cfg.set_main_option("script_location", str(repo_root / "migrations"))
        expected = ScriptDirectory.from_config(cfg).get_current_head()

        async with self.engine.connect() as conn:
            try:
                current = await conn.scalar(sql_text("SELECT version_num FROM alembic_version"))
            except Exception:
                current = None

        if current != expected:
            raise RuntimeError(
                f"Database schema is at revision {current!r} but the code expects {expected!r}. "
                "Run `alembic upgrade head` before starting the service."
            )

    async def run_in_session(
        self,
        operation: "Callable[[AsyncSession], Awaitable[Any]]",
        *,
        retries: int = 3,
        base_delay: float = 0.25,
    ) -> Any:
        """Run one unit of work in its own transaction, retrying transient conflicts.

        Deadlocks and serialization failures are normal under concurrency: two
        writers touching the same rows in a different order, or a migration
        taking a table lock while a collector inserts. PostgreSQL resolves them
        by aborting one side, and the correct response is to retry the whole
        transaction rather than to surface a stack trace.

        Each call gets a fresh session, so a failure rolls back only its own
        unit of work and releases its locks immediately.
        """
        attempt = 0
        while True:
            try:
                async with self.session() as session:
                    return await operation(session)
            except Exception as exc:  # noqa: BLE001 - re-raised unless transient
                attempt += 1
                if attempt > retries or not is_transient_db_error(exc):
                    raise
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, base_delay)
                logger.warning(
                    "Transient database conflict (%s); retrying in %.2fs (attempt %d/%d)",
                    type(getattr(exc, "orig", exc)).__name__, delay, attempt, retries,
                )
                await asyncio.sleep(delay)

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


@asynccontextmanager
async def advisory_lock(session: AsyncSession, key: str) -> AsyncGenerator[bool, None]:
    """Best-effort distributed lock for a scheduled job window (spec 18).

    Uses a PostgreSQL session-level advisory lock so two workers cannot run the
    same collector window concurrently and duplicate outbound requests. On
    SQLite (local test runs) there is a single writer anyway, so the lock is a
    no-op that always grants.
    """
    dialect = session.bind.dialect.name if session.bind is not None else ""
    if dialect != "postgresql":
        yield True
        return

    lock_id = int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big", signed=True)
    acquired = bool(await session.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_id}))
    try:
        yield acquired
    finally:
        if acquired:
            await session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_id})


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for DB sessions."""
    async with db_manager.session() as session:
        yield session
