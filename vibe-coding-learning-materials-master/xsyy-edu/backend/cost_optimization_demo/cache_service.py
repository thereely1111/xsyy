"""教学内容缓存服务（Redis 优先）。

任务对应：
- 任务一 / 第二层缓存：对题目输入做确定性哈希，缓存教学内容，命中即跳过模型调用。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
from typing import Any, Optional

try:
    from .config import settings
except ImportError:  # pragma: no cover
    from config import settings

logger = logging.getLogger(__name__)

try:
    redis = importlib.import_module("redis")
except ImportError:  # pragma: no cover
    redis = None


class TeachingCacheService:
    """缓存服务：Redis 主存储，内存兜底。"""

    def __init__(self) -> None:
        self._memory_cache: dict[str, str] = {}
        self._redis_client = None
        self._prefix = settings.cache.key_prefix
        self._ttl = settings.cache.ttl_seconds

        if redis is None:
            logger.warning("未安装 redis 包，自动使用内存缓存兜底。")
            return

        try:
            self._redis_client = redis.Redis.from_url(
                settings.cache.redis_url,
                decode_responses=True,
                socket_connect_timeout=settings.cache.connect_timeout_seconds,
            )
            self._redis_client.ping()
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis 不可用（%s），自动使用内存缓存兜底。", exc)
            self._redis_client = None

    @staticmethod
    def build_prompt_hash(problem: str, difficulty: str, extra_context: Optional[dict[str, Any]] = None) -> str:
        """根据决定输出的输入字段构建稳定哈希。"""
        normalized = {
            "problem": (problem or "").strip(),
            "difficulty": (difficulty or "").strip().lower(),
            "extra_context": extra_context or {},
        }
        payload = json.dumps(normalized, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _build_cache_key(self, prompt_hash: str) -> str:
        return f"{self._prefix}:{prompt_hash}"

    def get(self, prompt_hash: str) -> Optional[str]:
        key = self._build_cache_key(prompt_hash)

        if self._redis_client is not None:
            try:
                return self._redis_client.get(key)
            except Exception as exc:  # pragma: no cover
                logger.warning("Redis 读取失败（%s），回退到内存缓存。", exc)

        return self._memory_cache.get(key)

    def set(self, prompt_hash: str, teaching_content: str, ttl_seconds: Optional[int] = None) -> None:
        key = self._build_cache_key(prompt_hash)
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl

        if self._redis_client is not None:
            try:
                self._redis_client.setex(key, ttl, teaching_content)
                return
            except Exception as exc:  # pragma: no cover
                logger.warning("Redis 写入失败（%s），回退到内存缓存。", exc)

        self._memory_cache[key] = teaching_content

    def delete(self, prompt_hash: str) -> None:
        key = self._build_cache_key(prompt_hash)

        if self._redis_client is not None:
            try:
                self._redis_client.delete(key)
            except Exception as exc:  # pragma: no cover
                logger.warning("Redis 删除失败（%s）。", exc)

        self._memory_cache.pop(key, None)
