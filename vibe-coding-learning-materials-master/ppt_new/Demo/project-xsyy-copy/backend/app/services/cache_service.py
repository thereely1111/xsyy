import redis.asyncio as redis
import json
import logging
from typing import Optional, Any
from app.config import settings

logger = logging.getLogger(__name__)


class CacheService:
    _instance: Optional["CacheService"] = None
    _redis: Optional[redis.Redis] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._redis is None:
            self._connect()

    async def _connect(self):
        try:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True
            )
            await self._redis.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}")
            self._redis = None

    async def get(self, key: str) -> Optional[Any]:
        if not self._redis:
            return None

        try:
            data = await self._redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Cache get failed: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = 300):
        if not self._redis:
            return

        try:
            await self._redis.setex(key, ttl, json.dumps(value))
        except Exception as e:
            logger.error(f"Cache set failed: {e}")

    async def delete(self, key: str):
        if not self._redis:
            return

        try:
            await self._redis.delete(key)
        except Exception as e:
            logger.error(f"Cache delete failed: {e}")

    async def increment(self, key: str, ttl: int = 60) -> int:
        if not self._redis:
            return 0

        try:
            pipe = self._redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl)
            results = await pipe.execute()
            return results[0]
        except Exception as e:
            logger.error(f"Cache increment failed: {e}")
            return 0

    async def exists(self, key: str) -> bool:
        if not self._redis:
            return False

        try:
            return await self._redis.exists(key) > 0
        except Exception as e:
            logger.error(f"Cache exists check failed: {e}")
            return False


cache_service = CacheService()


def get_cache_service() -> CacheService:
    return cache_service
