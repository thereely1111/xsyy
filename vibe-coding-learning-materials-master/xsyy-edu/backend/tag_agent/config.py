# -*- coding: utf-8 -*-
"""标签识别智能体配置。

兼容 xsyy-edu 项目的 GPTsAPI_* 中转配置（kuaipao.pro，OpenAI 兼容接口）。
所有项均可通过环境变量或 `.env` 覆盖。
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_SEED_DIR = Path(__file__).resolve().parent / "seed_data"


class TagAgentSettings(BaseSettings):
    """标签识别智能体运行配置."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── LLM 超时（主/备模型统一走项目出口 kimi_config：KIMI_MODEL + BACKUP_MODEL_*，
    #    与 agent-platform 平台默认模型同步；此处不再单独配置模型）──
    llm_timeout: float = 180.0

    # ── 正式标签库种子文件（远程 DB 连通前使用；连通后由 tag_library 读取 DB）──
    framework_seed_path: str = str(_SEED_DIR / "knowledge_tag_framework.json")
    keyword_index_path: str = str(_SEED_DIR / "keyword_index.json")

    # ── 远程标签库（配置后优先从 knowledge_tag_framework 表读取）──
    # 同时认 TAG_AGENT_REMOTE_DB_URL（.env.example 命名）与 REMOTE_DB_URL
    remote_db_url: str = Field(
        default="",
        validation_alias=AliasChoices("TAG_AGENT_REMOTE_DB_URL", "REMOTE_DB_URL"),
    )

    # ── 分层置信度阈值（方案"十、准确率保障机制"）──
    # 2026-09-18：域/年级 0.85→0.75，与章/标签阈值对齐（qwen3.8-flash 打分偏保守，
    # 0.85 曾导致第一步持续 low_confidence 降级 legacy）
    domain_conf_threshold: float = 0.75      # 知识域
    grade_conf_threshold: float = 0.75       # 年级
    chapter_conf_threshold: float = 0.75     # 章/单元
    tag_conf_threshold: float = 0.75         # 知识点标签
    keyword_conf_threshold: float = 0.60     # 关键词命中

    # ── 新标签生成前相似度阈值：高于该值视为重复，禁止生成 ──
    new_tag_similarity_threshold: float = 0.85

    @property
    def seed_path(self) -> Path:
        return Path(self.framework_seed_path)

    @property
    def keyword_store_path(self) -> Path:
        return Path(self.keyword_index_path)


def get_tag_agent_settings() -> TagAgentSettings:
    """获取全局标签识别智能体配置（单例）. """
    return TagAgentSettings()


# ── 一体化接入配置（进程内直连，保留兼容读取 .env）────────────────────────


def get_agent_platform_url() -> str:
    """兼容保留：一体化后不使用独立 9000 服务，返回自身地址占位."""
    return os.getenv("AGENT_PLATFORM_URL", "http://127.0.0.1:9000").rstrip("/")


def get_agent_platform_user_id() -> str:
    """兼容保留：一体化后不再使用 X-User-ID 转发."""
    return os.getenv("AGENT_PLATFORM_X_USER_ID", "admin")


def get_agent_request_timeout() -> float:
    return float(os.getenv("AGENT_PLATFORM_TIMEOUT", "180"))


def get_recognition_engine() -> str:
    """标签识别引擎开关：agent | legacy | dual.

    - agent ：使用智能体识别（进程内 orchestrator）
    - legacy：使用原有提示词识别（knowledge_tag_injector）
    - dual  ：双跑（agent 优先，失败降级 legacy；用于灰度对比）
    默认 dual，保证平稳过渡。
    """
    mode = os.getenv("TAG_RECOGNITION_ENGINE", "dual").strip().lower()
    if mode not in ("agent", "legacy", "dual"):
        mode = "dual"
    return mode

# ============================================================================
# P1.5 补丁：追加到 backend/tag_agent/config.py 末尾
# 作用：标签增强学习的总开关 + 每日 LLM 调用配额。
# 合并方式：整段复制到 config.py 末尾即可（已 import os）。
# 默认值：开关开启、日配额 20（仅“标签确实变更”才触发，词库已足够判词跳过，风险可控）。
# ============================================================================

def get_label_learning_enabled() -> bool:
    """P1.5 标签修改学习总开关（LABEL_LEARNING_ENABLED）。

    - true / 1 / yes / on  → 启用（默认）
    - false / 0 / no / off → 关闭（不生成任何增强建议）
    """
    return os.getenv("LABEL_LEARNING_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    )


def get_label_learning_daily_quota() -> int:
    """P1.5 每日生成建议配额（LABEL_LEARNING_DAILY_QUOTA），防止误点刷调用。"""
    try:
        return int(os.getenv("LABEL_LEARNING_DAILY_QUOTA", "20"))
    except (TypeError, ValueError):
        return 20
# ============================================================================
# P3 补丁：追加到 backend/tag_agent/config.py 末尾
# 作用：相似题复用总开关 + 阈值 + 题型沉淀阈值。合并方式：整段复制末尾即可。
# 默认值：开关关闭（默认不触发，先灰度）、手动阈值 0.85、自动阈值 0.95、沉淀阈值 5、图片题保守关闭。
# ============================================================================

def get_reuse_enabled() -> bool:
    """P3 相似题复用总开关（REUSE_ENABLED）。默认 false（先灰度，确认无误再开启）。"""
    return os.getenv("REUSE_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def get_reuse_auto_apply() -> bool:
    """自动复用（跳过生成）总开关（REUSE_AUTO_APPLY）。默认 false：先全部走人工确认队列，跑通后再开。"""
    return os.getenv("REUSE_AUTO_APPLY", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def get_reuse_auto_threshold() -> float:
    """高置信自动复用阈值（REUSE_AUTO_THRESHOLD），≥ 此值且 REUSE_AUTO_APPLY=true 才跳过生成。"""
    try:
        return float(os.getenv("REUSE_AUTO_THRESHOLD", "0.95"))
    except (TypeError, ValueError):
        return 0.95


def get_reuse_manual_threshold() -> float:
    """中置信人工确认阈值（REUSE_MANUAL_THRESHOLD），≥ 此值进复用建议队列。"""
    try:
        return float(os.getenv("REUSE_MANUAL_THRESHOLD", "0.85"))
    except (TypeError, ValueError):
        return 0.85


def get_reuse_image_enabled() -> bool:
    """图片题复用开关（REUSE_IMAGE_ENABLED）。默认 false：构图依赖附图，保守关闭。"""
    return os.getenv("REUSE_IMAGE_ENABLED", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )


def get_reuse_sediment_threshold() -> int:
    """题型沉淀阈值（REUSE_SEDIMENT_THRESHOLD）：同 method_signature 成功复用 ≥ 此值触发草稿。"""
    try:
        return int(os.getenv("REUSE_SEDIMENT_THRESHOLD", "5"))
    except (TypeError, ValueError):
        return 5
