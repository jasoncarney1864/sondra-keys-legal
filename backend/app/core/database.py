"""
Asynchronous database setup using SQLAlchemy 2.x async extension.

This module manages the async engine lifecycle and session factory.
The engine is created at application startup and disposed on shutdown
via the lifespan context manager in main.py.

Reference in main.py:
    from backend.app.core.database import engine, get_engine

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup — engine already created at import time
        yield
        # Shutdown
        await get_engine().dispose()
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)

from backend.app.core.config import settings
from backend.app.models.db import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Async Engine Initialization
# ---------------------------------------------------------------------------

# Build engine arguments dynamically based on the database dialect
engine_kwargs = {}

# Mapped through the nested 'database' configuration group
if not settings.database.database_url.startswith("sqlite"):
    # Only apply connection pooling parameters to production databases (e.g., Postgres)
    engine_kwargs["pool_size"] = 10  
    engine_kwargs["max_overflow"] = 20  
else:
    # SQLite serializes writers. Without a busy timeout, concurrent writes from
    # multiple uvicorn workers fail immediately with "database is locked".
    # Wait up to 30s for the lock to clear instead of erroring out.
    engine_kwargs["connect_args"] = {"timeout": 30}

engine: AsyncEngine = create_async_engine(
    settings.database.database_url,
    **engine_kwargs
)


if settings.database.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ANN001
        """Enable WAL journaling and a busy timeout for better write concurrency."""
        cursor = dbapi_connection.cursor()
        try:
            # Set the busy timeout first so every subsequent statement (including
            # the journal-mode switch below) waits for locks instead of failing.
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            # WAL is a persistent, file-level property; only the first connection
            # needs to set it. During a multi-worker cold start several
            # connections may race to switch journal modes, which can briefly
            # report "database is locked". Tolerate that — once any connection
            # wins, the mode sticks for all future connections.
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:  # noqa: BLE001 - transient startup lock is non-fatal
                pass
        finally:
            cursor.close()

# ---------------------------------------------------------------------------
# Async Session Factory
# ---------------------------------------------------------------------------

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep objects in memory after commit
    autocommit=False,  # Require explicit commit
    autoflush=False,  # Require explicit flush
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_engine() -> AsyncEngine:
    """
    Retrieve the global async engine.

    Used by main.py lifespan to dispose the pool on shutdown.
    """
    return engine


async def init_db() -> None:
    """
    Create all database tables (idempotent).

    Called during application startup. Skips creation if tables already exist,
    including benign multi-worker SQLite startup races.
    """
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if settings.database.database_url.startswith("sqlite"):
                await _apply_sqlite_additive_migrations(conn)
        logger.info("database_schema_created_or_verified")
    except OperationalError as e:
        error_text = str(e).lower()
        if "already exists" in error_text:
            logger.info("database_schema_already_initialized")
            return
        raise


async def _sqlite_column_exists(conn, table_name: str, column_name: str) -> bool:
    """Return True if SQLite table contains the specified column."""
    rows = (
        await conn.execute(text(f"PRAGMA table_info({table_name})"))
    ).fetchall()
    return any(row[1] == column_name for row in rows)


async def _apply_sqlite_additive_migrations(conn) -> None:
    """Apply additive SQLite migrations for backward-compatible columns."""
    table_exists = (
        await conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='document_records'"
            )
        )
    ).fetchone()
    if not table_exists:
        return

    additive_columns = [
        ("uploaded_by_user_id", "TEXT"),
        ("parsed_json_blob_name", "TEXT"),
        ("parser_version", "TEXT"),
        ("parsed_json_cached_at", "DATETIME"),
    ]

    for column_name, column_type in additive_columns:
        if not await _sqlite_column_exists(conn, "document_records", column_name):
            await conn.execute(
                text(
                    "ALTER TABLE document_records "
                    f"ADD COLUMN {column_name} {column_type}"
                )
            )


async def drop_db() -> None:
    """
    Drop all database tables.

    Used for testing and development cleanup only.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ---------------------------------------------------------------------------
# Session context manager (advanced usage)
# ---------------------------------------------------------------------------


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async generator for manual session acquisition.

    Used primarily by get_db_session() dependency in dependencies.py.
    Routes should NOT call this directly; they should use:
        session: AsyncSession = Depends(get_db_session)
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"session_rollback_on_error: {type(e).__name__}")
            raise
        finally:
            await session.close()
