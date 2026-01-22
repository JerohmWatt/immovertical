import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel
from typing import AsyncGenerator

# Import configuration
try:
    from .config import config as app_config
    DATABASE_URL = app_config.database.url
    POOL_SIZE = app_config.database.pool_size
    MAX_OVERFLOW = app_config.database.max_overflow
    POOL_TIMEOUT = app_config.database.pool_timeout
    POOL_RECYCLE = app_config.database.pool_recycle
    ECHO = app_config.database.echo
except ImportError:
    # Fallback for backwards compatibility
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be set")
    POOL_SIZE = int(os.getenv("DATABASE_POOL_SIZE", "20"))
    MAX_OVERFLOW = int(os.getenv("DATABASE_MAX_OVERFLOW", "10"))
    POOL_TIMEOUT = int(os.getenv("DATABASE_POOL_TIMEOUT", "30"))
    POOL_RECYCLE = int(os.getenv("DATABASE_POOL_RECYCLE", "3600"))
    ECHO = os.getenv("DATABASE_ECHO", "false").lower() == "true"

# Ensure the driver is asyncpg for PostgreSQL
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Create the async engine with proper pool configuration
engine = create_async_engine(
    DATABASE_URL,
    echo=ECHO,
    future=True,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,  # Verify connections before using
)

# Session factory
async_session_factory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def init_db() -> None:
    """Initialize the database (create tables if they don't exist)."""
    async with engine.begin() as conn:
        # SQLModel.metadata.create_all(conn) is not directly supported for async
        # We use run_sync for this
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for obtaining an async session."""
    async with async_session_factory() as session:
        yield session
