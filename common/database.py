import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel
from typing import AsyncGenerator

# Fetch DATABASE_URL from environment variables
# Format: postgresql+asyncpg://user:password@host:port/dbname
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql+asyncpg://postgres:postgres@localhost:5432/immovertical"
)

# Create the async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
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
