"""
Async SQLAlchemy engine, session factory ve declarative Base.

FastAPI dependency (`get_db`) her istek için ayrı bir AsyncSession açar
ve istek bitiminde kapatır. Modeller `Base`'den türetilir.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Tüm ORM modellerinin türediği temel sınıf."""
    pass


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_pre_ping=True,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI route'larında `Depends(get_db)` ile kullanılan session sağlayıcı."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
