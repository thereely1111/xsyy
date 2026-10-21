# -*- coding: utf-8 -*-
"""xsyy 侧智能体接入配置（读取 .env）.

新增配置项（backend/.env）：
    AGENT_PLATFORM_URL=http://127.0.0.1:9000   # agent-platform 服务地址
    AGENT_PLATFORM_X_USER_ID=admin             # 转发时使用的用户标识（agent-platform dev 模式）
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_backend_dir / ".env")


def get_agent_platform_url() -> str:
    """agent-platform 服务地址（默认本机 9000 端口）. """
    return os.getenv("AGENT_PLATFORM_URL", "http://127.0.0.1:9000").rstrip("/")


def get_agent_platform_user_id() -> str:
    """转发请求时使用的用户标识（agent-platform 的 X-User-ID，dev 模式自动赋 DEVELOPER 角色）. """
    return os.getenv("AGENT_PLATFORM_X_USER_ID", "admin")


def get_agent_request_timeout() -> float:
    return float(os.getenv("AGENT_PLATFORM_TIMEOUT", "180"))


def get_recognition_engine() -> str:
    """标签识别引擎开关：agent | legacy | dual.

    - agent ：使用智能体识别（agent-platform /tag-agent/recognize）
    - legacy：使用原有提示词识别（knowledge_tag_injector）
    - dual  ：双跑（agent 优先，失败降级 legacy；用于灰度对比）
    默认 dual，保证平稳过渡。
    """
    mode = os.getenv("TAG_RECOGNITION_ENGINE", "dual").strip().lower()
    if mode not in ("agent", "legacy", "dual"):
        mode = "dual"
    return mode
