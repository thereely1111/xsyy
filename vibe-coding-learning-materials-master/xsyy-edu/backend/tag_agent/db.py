# -*- coding: utf-8 -*-
"""一体化部署：智能体数据访问层（独立异步引擎 + 会话工厂）.

标签智能体本体重新部署回 xsyy 进程（2026-08-31 一体化）：使用**独立异步引擎**
连接远程 MySQL 业务库（test_xsyy / xsyy），与 xsyy 同步 SessionLocal 并存。
四张智能体表使用独立 declarative Base（TagBase），只承载智能体表，避免把
业务表模型带进智能体建表/查询；四张表与业务表同库，保证审核队列天然一致。

连接串：优先 TAG_AGENT_REMOTE_DB_URL（.env，推荐），否则回退 DATABASE_URL。
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)

# 独立 declarative base：仅承载智能体四张表，避免把业务表模型建进远程 MySQL 业务库
class TagBase(DeclarativeBase):
    """标签智能体四张表的 declarative base（绑定远程 MySQL 业务库）. """


Base = TagBase  # 兼容 models.py 的 `from tag_agent.db import Base`

_engine = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _resolve_db_url() -> str:
    # .env 由 pydantic settings 加载，os.getenv 读不到，因此优先从 settings 取
    try:
        from tag_agent.config import get_tag_agent_settings
        remote = get_tag_agent_settings().remote_db_url
        if remote:
            return remote
    except Exception:  # noqa: BLE001
        pass
    import os
    return os.getenv("DATABASE_URL", "").strip()


def get_engine():
    """获取（惰性创建）智能体异步引擎."""
    global _engine
    if _engine is None:
        url = _resolve_db_url()
        # 同步 URL 转异步驱动：mysql+pymysql → mysql+aiomysql
        if url.startswith("mysql+pymysql"):
            url = url.replace("mysql+pymysql", "mysql+aiomysql", 1)
        _engine = create_async_engine(url, pool_pre_ping=True, pool_recycle=3600)
        logger.info("智能体异步引擎就绪（%s）", url.split("@")[-1].split("/")[0])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(), class_=AsyncSession, expire_on_commit=False,
        )
    return _session_factory


async def create_tables() -> None:
    """建表（幂等）：智能体四张表 + 轻量迁移（补阶段二新增列）. """
    from sqlalchemy import text

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # SQLite 才需要 ALTER 迁移；MySQL 由建表 SQL 脚本保证（生产用 SQL 脚本）
        if str(engine.url).startswith("sqlite"):
            result = await conn.execute(text("PRAGMA table_info(tag_agent_pending_tags)"))
            cols = {row[1] for row in result}
            add_columns = {
                "operation": "VARCHAR(20) DEFAULT 'add'",
                "target_domain": "VARCHAR(50) DEFAULT ''",
                "target_grade": "VARCHAR(10) DEFAULT ''",
                "target_chapter": "VARCHAR(100) DEFAULT ''",
                "target_tag": "VARCHAR(100) DEFAULT ''",
                "before_snapshot": "TEXT",
                "after_snapshot": "TEXT",
                "evidence": "TEXT DEFAULT ''",
            }
            for col, ddl in add_columns.items():
                if col not in cols:
                    await conn.execute(
                        text(f"ALTER TABLE tag_agent_pending_tags ADD COLUMN {col} {ddl}")
                    )


async def get_db():
    """FastAPI 依赖：智能体异步会话."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def close_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    _session_factory = None
