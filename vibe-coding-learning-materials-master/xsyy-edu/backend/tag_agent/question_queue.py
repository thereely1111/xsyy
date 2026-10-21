# -*- coding: utf-8 -*-
"""题目标签审核队列应用（阶段三：题目级标签全人工审核的宿主侧落地）.

agent-platform 的 /tag-agent/question-proposals/{id}/review 审核通过后返回
knowledge_tags；本模块负责把审核结果应用到 xsyy 的 teachings 表，
并支持「已审核题目」状态查询。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def apply_knowledge_tags_to_teaching(
    teaching,
    knowledge_tags: Optional[dict],
    *,
    task_id: str = "",
) -> bool:
    """把审核通过的 knowledge_tags 写入 teaching 记录（含 metadata 同步）.

    Args:
        teaching: SQLAlchemy Teaching ORM 对象（未 commit）
        knowledge_tags: 审核返回的标签结构（含 version/grade/main_tag/sub_tags）
        task_id: 题目 task_id（日志用）

    Returns:
        True 表示已应用；False 表示 teaching 为空或知识标签为空。
    """
    if teaching is None:
        logger.warning("[题目审核应用] teaching 不存在: %s", task_id)
        return False
    if not knowledge_tags or not knowledge_tags.get("main_tag"):
        logger.warning("[题目审核应用] knowledge_tags 不完整，跳过: %s", task_id)
        return False

    teaching.knowledge_tags = knowledge_tags
    # 若 metadata 有标签字段，同步写入
    try:
        meta = teaching.metadata
        if isinstance(meta, dict):
            meta["knowledge_tags"] = knowledge_tags
            meta["tag_source"] = knowledge_tags.get("tag_source", "official")
            meta["tag_review_status"] = knowledge_tags.get("pending_review_status", "approved")
            teaching.metadata = meta
    except Exception:  # noqa: BLE001
        pass  # metadata 字段缺失时忽略，knowledge_tags 已写入
    logger.info("[题目审核应用] 已写入题目标签 task_id=%s → %s", task_id, knowledge_tags.get("main_tag"))
    return True
