"""数据库连接配置模块"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent.parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

# 从环境变量获取数据库连接字符串
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:password@localhost:3306/xsyy?charset=utf8mb4"
)

# 创建数据库引擎
# 连接池配置：默认值按公网并发场景调优（2026-09-01），
# 本地/测试/生产可通过 .env 独立覆盖（DB_POOL_SIZE / DB_MAX_OVERFLOW / DB_POOL_RECYCLE）。
# 峰值连接数 = workers × (pool_size + max_overflow)：
#   4 workers × (10 + 20) = 最多 120 连接（实测生产/测试 max_connections=1000，充足）
# 注意：不设置 pool_timeout（沿用 SQLAlchemy 默认 30s 排队）。
#   历史教训（2026-09-01）：曾设 10s 快速失败，公网上「创建教学任务」接口
#   在连接池排队超 10s 即报「创建失败」，但后台任务已启动继续运行，
#   造成「用户看到失败、后台仍在生成」的状态混乱。创建类接口宁可多等也不可快速失败；
#   连接占用时间过长的根因（N+1/往返过多）由减少查询次数解决，而不是用超时硬切。
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "1800"))

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # 连接前检查连接是否有效（远程库必备）
    pool_recycle=POOL_RECYCLE,   # 回收空闲连接（远小于 MySQL wait_timeout=28800，安全）
    pool_size=POOL_SIZE,         # 每个进程基础连接池大小
    max_overflow=MAX_OVERFLOW,   # 每个进程最大溢出连接数
    echo=False           # 生产环境设为 False，开发环境可设为 True 查看 SQL
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 创建基础模型类
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """获取数据库会话（依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库（创建所有表）"""
    # 导入所有模型以确保它们被注册到 Base.metadata
    from database import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "users" in inspector.get_table_names():
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "current_session_id" not in user_columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN current_session_id VARCHAR(128) NULL"))

    if "comments" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("comments")}
        if "parent_id" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE comments ADD COLUMN parent_id VARCHAR(36)"))
    # 公告表兼容旧库：通知分类与首页公告展示开关。
    if "announcements" in inspector.get_table_names():
        ann_cols = {column["name"] for column in inspector.get_columns("announcements")}
        if "category" not in ann_cols:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE announcements ADD COLUMN category VARCHAR(20) NOT NULL DEFAULT 'system'")
                )
        if "is_home_banner" not in ann_cols:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE announcements ADD COLUMN is_home_banner BOOLEAN NOT NULL DEFAULT FALSE")
                )

        # 新建表会由 SQLAlchemy 根据模型创建该索引；仅为已存在的旧表补齐。
        ann_indexes = {index["name"] for index in inspect(engine).get_indexes("announcements")}
        if "ix_announcements_is_home_banner" not in ann_indexes:
            with engine.begin() as connection:
                connection.execute(
                    text("CREATE INDEX ix_announcements_is_home_banner ON announcements (is_home_banner)")
                )

    if "teachings" in inspector.get_table_names():
        t_cols = {column["name"] for column in inspector.get_columns("teachings")}
        if "is_pinned" not in t_cols:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE teachings ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT 0 AFTER view_count"))

    # 官方邀请码表初始化：若为空，写入历史硬编码官方码 XSYY2026，使其纳入 official_invite_codes 统一管理
    if "official_invite_codes" in inspector.get_table_names():
        try:
            from database.models import OfficialInviteCode
            with SessionLocal() as seed_db:
                if seed_db.query(OfficialInviteCode).count() == 0:
                    seed_db.add(
                        OfficialInviteCode(
                            code="XSYY2026",
                            is_active=True,
                            description="初始官方邀请码（历史硬编码码迁入数据库）",
                            created_by="system",
                        )
                    )
                    seed_db.commit()
        except Exception:
            # 表尚未就绪或数据库暂不可用时跳过，不阻断启动
            pass

