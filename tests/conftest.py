"""Shared test fixtures.

Tests run against the PostgreSQL instance from docker-compose so that JSONB
behaviour, the spec's index types and the Alembic migrations themselves are all
exercised. Set TEST_DATABASE_URL to point somewhere else.

The schema is built once per session by running the real migration chain - a
migration that fails to apply therefore fails the suite, rather than being
papered over by ``metadata.create_all``. Each test then runs inside a
transaction that is rolled back, so tests stay isolated and fast.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ecd:ecd_dev_password@localhost:55432/ecd_test",
)


def _run_migrations(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def database_url() -> str:
    return TEST_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema(database_url: str) -> None:
    """Build the test schema once, via the real migration chain."""
    os.environ["DATABASE_URL"] = database_url
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture
async def db_engine(database_url: str):
    engine = create_async_engine(
        database_url,
        echo=False,
        json_serializer=lambda obj: json.dumps(obj, default=str),
        pool_pre_ping=True,
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_db(db_engine) -> AsyncSession:
    """A session bound to a transaction that is always rolled back."""
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )
        session = session_factory()
        try:
            yield session
        finally:
            await session.close()
            if transaction.is_active:
                await transaction.rollback()
