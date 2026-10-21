# -*- coding: utf-8 -*-
"""agent-platform 代理转发（管理后台审核页使用）.

把 xsyy 管理后台的 /api/admin/tag-agent/* 请求转发到 agent-platform 的
/tag-agent/* 接口，附带 X-User-ID（agent-platform dev 模式自动赋予
DEVELOPER 角色，满足 require_role 校验）。生产环境可改为 Bearer JWT。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from tag_agent.config import (
    get_agent_platform_url,
    get_agent_platform_user_id,
    get_agent_request_timeout,
)

logger = logging.getLogger(__name__)


async def proxy_to_agent_platform(
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> dict:
    """转发请求到 agent-platform /tag-agent/{path}，返回 JSON 结果.

    Args:
        method: GET / POST / PUT / DELETE
        path:  agent-platform 侧路径（不含 /tag-agent 前缀，如 "pending"、"pending/x/review"）
        params: 查询参数
        json_body: JSON 请求体

    Returns:
        上游 JSON 响应体

    Raises:
        RuntimeError: 网络错误或上游非 2xx（detail 透传）。
    """
    base = get_agent_platform_url()
    url = f"{base}/tag-agent/{path.lstrip('/')}"
    headers = {"X-User-ID": get_agent_platform_user_id()}
    timeout = get_agent_request_timeout()

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method.upper(),
                url,
                params=params or {},
                json=json_body,
                headers=headers,
            )
    except httpx.TimeoutException:
        logger.warning("转发 agent-platform 超时: %s %s", method, url)
        raise RuntimeError(f"智能体平台响应超时（{timeout}s），请确认 agent-platform 已启动") from None
    except httpx.HTTPError as e:
        logger.warning("转发 agent-platform 网络错误: %s %s → %s", method, url, e)
        raise RuntimeError(f"无法连接智能体平台（{base}），请确认服务已启动") from None

    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        logger.warning("agent-platform 返回 %s: %s", resp.status_code, detail)
        raise RuntimeError(detail or f"智能体平台返回 HTTP {resp.status_code}")

    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"raw": resp.text}
