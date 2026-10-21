"""模型配置统一出口（所有模型调用只从这里读 .env，禁止在各业务代码里直接另配）

.env 配置项:
    KIMI_MODEL            文本主模型名称 (默认 kimi-k2.7-code)
    KIMI_API_KEY          文本主模型 API 密钥
    KIMI_BASE_URL         文本主模型 API 地址 (默认 https://api.moonshot.cn/v1)
    BACKUP_MODEL_API_KEY  文本备用模型 API 密钥（默认模型超时/网络异常时优先切换）
    BACKUP_MODEL_BASE_URL 文本备用模型 API 地址
    BACKUP_MODEL_NAME     文本备用模型名称
    GPTsAPI_KEY           生图主模型 API 密钥（封面预览图）
    GPTsAPI_BASE          生图主模型 API 地址 (默认 https://api.gptsapi.net/v1)
    GPTsAPI_IMAGE_MODEL   生图主模型名称 (默认 gpt-image-2)
    BACKUP_IMAGE_MODEL_API_KEY  生图备用模型 API 密钥（封面生图专用一级兜底）
    BACKUP_IMAGE_MODEL_BASE_URL 生图备用模型 API 地址
    BACKUP_IMAGE_MODEL_NAME     生图备用模型名称
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict

# 确保 .env 已加载（在 import 时执行）
from dotenv import load_dotenv
_backend_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_backend_dir / ".env")

# ---------------------------------------------------------------------------
# 环境变量读取
# ---------------------------------------------------------------------------

_GENERAL_MODEL = os.getenv("KIMI_MODEL", "kimi-k2.7-code")
_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")

# 备用模型（默认模型超时/网络异常时优先切换，动画与封面共用）
_BACKUP_API_KEY = os.getenv("BACKUP_MODEL_API_KEY", "").strip()
_BACKUP_BASE_URL = os.getenv("BACKUP_MODEL_BASE_URL", "").strip()
_BACKUP_MODEL = os.getenv("BACKUP_MODEL_NAME", "").strip()

# 生图模型（封面预览图，GPTsAPI 中转）
_IMAGE_API_KEY = os.getenv("GPTsAPI_KEY", "").strip()
_IMAGE_BASE_URL = os.getenv("GPTsAPI_BASE", "https://api.gptsapi.net/v1").strip()
_IMAGE_MODEL = os.getenv("GPTsAPI_IMAGE_MODEL", "gpt-image-2").strip()

# 生图备用模型（封面生图专用一级兜底）
_BACKUP_IMAGE_API_KEY = os.getenv("BACKUP_IMAGE_MODEL_API_KEY", "").strip()
_BACKUP_IMAGE_BASE_URL = os.getenv("BACKUP_IMAGE_MODEL_BASE_URL", "").strip()
_BACKUP_IMAGE_MODEL = os.getenv("BACKUP_IMAGE_MODEL_NAME", "").strip()


# ---------------------------------------------------------------------------
# 通用模型 API
# ---------------------------------------------------------------------------

def get_active_model() -> str:
    """返回模型名称"""
    return _GENERAL_MODEL


def get_base_url() -> str:
    """返回 Kimi API 地址"""
    return _BASE_URL


def get_api_key() -> str:
    """返回主模型 API 密钥（未配置时返回空串）"""
    return os.getenv("KIMI_API_KEY", "").strip()


def get_params_for_model(model_name: str) -> Dict[str, Any]:
    """返回指定模型对应的 API 额外参数"""
    model_lower = (model_name or "").lower()
    if model_lower.startswith("kimi-k2"):
        return {"extra_body": {"thinking": {"type": "enabled"}}}
    return {}


def get_active_params() -> Dict[str, Any]:
    """返回模型对应的 API 额外参数"""
    return get_params_for_model(_GENERAL_MODEL)


# ---------------------------------------------------------------------------
# 备用模型 API
# ---------------------------------------------------------------------------

def get_backup_api_key() -> str:
    """返回备用模型 API 密钥（未配置时返回空串）"""
    return _BACKUP_API_KEY


def get_backup_base_url() -> str:
    """返回备用模型 API 地址（未配置时返回空串）"""
    return _BACKUP_BASE_URL


def get_backup_model() -> str:
    """返回备用模型名称（未配置时返回空串）"""
    return _BACKUP_MODEL


def is_backup_configured() -> bool:
    """备用模型是否配置完整（密钥 + 地址 + 模型名三者齐备才启用）"""
    return bool(_BACKUP_API_KEY and _BACKUP_BASE_URL and _BACKUP_MODEL)


def get_backup_params() -> Dict[str, Any]:
    """返回备用模型对应的 API 额外参数"""
    return get_params_for_model(_BACKUP_MODEL)


# ---------------------------------------------------------------------------
# 生图模型 API（封面预览图，GPTsAPI 中转）
# ---------------------------------------------------------------------------

def get_image_api_key() -> str:
    """返回生图主模型 API 密钥（未配置时返回空串）"""
    return _IMAGE_API_KEY


def get_image_base_url() -> str:
    """返回生图主模型 API 地址"""
    return _IMAGE_BASE_URL


def get_image_model() -> str:
    """返回生图主模型名称"""
    return _IMAGE_MODEL


# ---------------------------------------------------------------------------
# 生图备用模型 API（封面生图专用一级兜底）
# ---------------------------------------------------------------------------

def get_backup_image_api_key() -> str:
    """返回生图备用模型 API 密钥（未配置时返回空串）"""
    return _BACKUP_IMAGE_API_KEY


def get_backup_image_base_url() -> str:
    """返回生图备用模型 API 地址（未配置时返回空串）"""
    return _BACKUP_IMAGE_BASE_URL


def get_backup_image_model() -> str:
    """返回生图备用模型名称（未配置时返回空串）"""
    return _BACKUP_IMAGE_MODEL


def is_backup_image_configured() -> bool:
    """生图备用模型是否配置完整（密钥 + 地址 + 模型名三者齐备才启用）"""
    return bool(_BACKUP_IMAGE_API_KEY and _BACKUP_IMAGE_BASE_URL and _BACKUP_IMAGE_MODEL)


def is_timeout_error(exc: Exception) -> bool:
    """判断异常是否为超时/连接类错误（触发切换到备用模型）。

    默认模型超时或网络异常时，优先用备用模型重试一次，而非直接降级/失败。
    除常规超时/连接异常外，还识别网关超时 HTTP 524：kuaipao.pro 网关约 120s
    无完整响应时返回 524，openai SDK 将其包装为 APIStatusError/InternalServerError
    （异常名不含 timeout），若不按状态码识别，默认模型 524 时将不会切备用模型。
    """
    try:
        from openai import APITimeoutError, APIConnectionError

        if isinstance(exc, (APITimeoutError, APIConnectionError)):
            return True
    except ImportError:  # 旧版 openai SDK 无独立异常类
        pass
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    try:
        from openai import APIStatusError

        if isinstance(exc, APIStatusError):
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 524:
                return True
    except ImportError:
        pass
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return "timeout" in name or "connection" in name or "read timed out" in msg or "524" in msg


def record_success() -> None:
    """记录一次成功调用（预留接口）"""
    pass


def record_failure() -> None:
    """记录一次失败调用（预留接口）"""
    pass
