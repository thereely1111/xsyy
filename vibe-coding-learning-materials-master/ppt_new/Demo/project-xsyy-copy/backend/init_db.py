from sqlalchemy import inspect
from app.database import async_engine, Base
from app.models import User, Problem, Application, Comment, Like, Favorite
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created successfully")


async def check_db_connection():
    try:
        async with async_engine.connect() as conn:
            await conn.execute("SELECT 1")
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


if __name__ == "__main__":
    import asyncio

    async def main():
        logger.info("Initializing database...")
        if await check_db_connection():
            await init_db()
            logger.info("Database initialization complete")
        else:
            logger.error("Cannot initialize database - connection failed")

    asyncio.run(main())
