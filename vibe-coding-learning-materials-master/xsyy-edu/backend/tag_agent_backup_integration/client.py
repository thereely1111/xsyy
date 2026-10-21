# -*- coding: utf-8 -*-
"""识别 HTTP 客户端（阶段三：接入 agent-platform 标签智能体）.

调用 agent-platform 的 /tag-agent/recognize 识别题目，结果经 compat.py
映射为 xsyy 既有 knowledge_tags 结构；失败/超时抛出 RuntimeError，
由调用方（pipeline.py / app.py）降级到 legacy 提示词识别。
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from tag_agent.config import (
    get_agent_platform_url,
    get_agent_platform_user_id,
    get_agent_request_timeout,
)

logger = logging.getLogger(__name__)


async def recognize_question(
    question: str,
    *,
    title: str = "",
    question_id: str = "",
    creator_id: str = "system",
    timeout: Optional[float] = None,
) -> dict:
    """调用智能体识别题目，返回 xsyy 兼容的识别结果.

    Returns:
        {
          "primary": {...} | None,     # 兼容 legacy 结构
          "second": None,
          "_meta": {"source", "confidence", "engine": "agent"},
          "knowledge_tags": {...} | None,   # 写入题目的标签结构
          "pending_tag_id": ...,
          "question_proposal_id": ...,
        }

    Raises:
        RuntimeError: 网络错误 / 上游错误 / 上游非 2xx。
    """
    base = get_agent_platform_url()
    url = f"{base}/tag-agent/recognize"
    body = {
        "question": question,
        "question_id": question_id or "",
        "creator_id": creator_id,
    }
    headers = {"X-User-ID": get_agent_platform_user_id()}
    tmo = timeout or get_agent_request_timeout()

    try:
        async with httpx.AsyncClient(timeout=tmo) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        logger.warning("智能体识别超时（%ss）：%s", tmo, question[:40])
        raise RuntimeError(f"智能体识别超时（{tmo}s）") from None
    except httpx.HTTPError as e:
        logger.warning("智能体识别网络错误: %s", e)
        raise RuntimeError(f"无法连接智能体平台（{base}）") from None

    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        logger.warning("智能体识别返回 %s: %s", resp.status_code, detail)
        raise RuntimeError(detail or f"智能体平台返回 HTTP {resp.status_code}")

    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        raise RuntimeError("智能体平台响应不是合法 JSON") from None

    return data


async def recognize_or_fallback(
    question: str,
    *,
    title: str = "",
    question_id: str = "",
    legacy_caller=None,
) -> dict:
    """智能体识别，失败自动降级 legacy（双保险）.

    Args:
        legacy_caller: async callable(question, title) → legacy 结果
                       （如 inject_knowledge_tags_full），供降级使用。

    Returns:
        (result_dict, engine) — result_dict 含 knowledge_tags 或 legacy 结构。
    """
    try:
        data = await recognize_question(
            question, title=title, question_id=question_id,
        )
        mapped = map_agent_result(data, question=question, title=title)
        return mapped, "agent"
    except Exception as e:  # noqa: BLE001
        logger.warning("智能体识别失败，降级 legacy: %s", e)
        if legacy_caller is not None:
            try:
                legacy = await legacy_caller(question, title)
                return legacy, "legacy"
            except Exception as e2:  # noqa: BLE001
                logger.error("legacy 识别也失败: %s", e2)
        return {"primary": None, "second": None}, "none"
