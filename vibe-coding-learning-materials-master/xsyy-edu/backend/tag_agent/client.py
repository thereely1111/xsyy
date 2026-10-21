# -*- coding: utf-8 -*-
"""识别客户端（一体化部署：进程内直调智能体编排器）.

智能体本体已随 xsyy 进程运行（2026-08-31 重新一体化），不再依赖独立
agent-platform 9000 服务；直接调用 tag_agent.orchestrator，结果经 compat.py
映射为 xsyy 结构；失败/异常由调用方（pipeline.py）降级到 legacy 提示词识别。

对外接口签名与原 HTTP 版保持一致（recognize_question / recognize_or_fallback）。
"""
from __future__ import annotations

import logging
from typing import Optional

from tag_agent.compat import map_agent_result
from tag_agent.config import get_tag_agent_settings
from tag_agent.orchestrator import TagAgentOrchestrator
from tag_agent.tag_library import TagLibrary

logger = logging.getLogger(__name__)

# 模块级单例（惰性初始化）：标签库 + 编排器
_library: Optional[TagLibrary] = None
_orchestrator: Optional[TagAgentOrchestrator] = None


def get_orchestrator() -> TagAgentOrchestrator:
    """获取进程内智能体编排器（惰性创建）. """
    global _library, _orchestrator
    if _orchestrator is None:
        settings = get_tag_agent_settings()
        _library = TagLibrary.load(settings)
        _orchestrator = TagAgentOrchestrator(_library, settings)
        logger.info("进程内智能体编排器就绪（标签库 source=%s）", _library.source)
    return _orchestrator


def reload_library() -> None:
    """重置进程内标签库/编排器单例（管理后台改库后调用）.

    仅置空惰性单例：下一次 get_orchestrator() 按最新库内容重建（约 0.5s 一次性开销）；
    正在进行的识别持有旧编排器引用，不受影响。
    """
    global _library, _orchestrator
    _library = None
    _orchestrator = None
    logger.info("[标签库] 进程内单例已重置，下次识别时按最新库重建")


async def recognize_question(
    question: str,
    *,
    title: str = "",
    question_id: str = "",
    creator_id: str = "system",
    timeout: Optional[float] = None,
    persist: bool = False,
) -> dict:
    """调用进程内智能体识别题目，返回 xsyy 兼容的识别结果.

    Args:
        persist: True 时把识别结果落地（识别日志 + 题目标签提案 +
                 预修改提案入审核队列），与 run_tag_completion /
                 管理后台「重新识别」同口径。生成主链路（pipeline）必须
                 开启，否则"新建标签提案"会被当成正式标签直接写题且
                 审核队列无记录（2026-09-11 排查修复）。

    Returns:
        同 compat.map_agent_result 的结构（primary/second/_meta/knowledge_tags 等）。

    Raises:
        RuntimeError: 识别失败（调用方据此降级 legacy）。
    """
    del title, timeout  # 进程内调用无需超时/标题透传
    try:
        outcome = await get_orchestrator().recognize(
            question,
            question_id=question_id,
            creator_id=creator_id,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("智能体识别失败: %s", e)
        raise RuntimeError(f"智能体识别失败: {e}") from None
    data: dict = {"outcome": outcome.to_dict()}
    if persist and question_id:
        try:
            from tag_agent import service as tag_service
            from tag_agent.db import get_session_factory

            factory = get_session_factory()
            async with factory() as session:

                async def _pending_names(domain: str, grade: str, chapter: str):
                    return await tag_service.list_pending_names(session, domain, grade, chapter)

                persisted = await tag_service.persist_recognition(
                    session, question=question, outcome=outcome,
                    question_id=question_id, creator_id=creator_id,
                )
            data["pending_tag_id"] = persisted.get("pending_tag_id", "")
            data["question_proposal_id"] = persisted.get("question_proposal_id", "")
        except Exception as e:  # noqa: BLE001
            # 落库失败不阻断识别结果返回，但必须留痕（下次仍可能重复提案）
            logger.warning("识别结果落库失败（question_id=%s）: %s", question_id, e)
    return map_agent_result(data, question=question, title="")


async def recognize_or_fallback(
    question: str,
    *,
    title: str = "",
    question_id: str = "",
    legacy_caller=None,
) -> tuple[dict, str]:
    """智能体识别，失败自动降级 legacy（双保险）.

    Args:
        legacy_caller: async callable(question, title) → legacy 结果
                       （如 inject_knowledge_tags_full），供降级使用。

    Returns:
        (result_dict, engine) — result_dict 含 knowledge_tags 或 legacy 结构。
    """
    try:
        mapped = await recognize_question(
            question, title=title, question_id=question_id,
        )
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
