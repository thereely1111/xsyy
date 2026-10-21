from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings


class Base(DeclarativeBase):
    pass


if "mysql+pymysql" in settings.DATABASE_URL:
    async_engine = create_async_engine(
        settings.DATABASE_URL.replace("mysql+pymysql", "mysql+aiomysql"),
        echo=settings.DATABASE_ECHO,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )
else:
    async_engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DATABASE_ECHO
    )

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
