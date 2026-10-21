# -*- coding: utf-8 -*-
"""结果兼容层：agent-platform 识别结果 → xsyy 既有 knowledge_tags 结构.

agent 返回（outcome.to_dict()）：
    {domain, grade, chapter, tag, confidence, action,
     knowledge_tags: {...}, pending_tag_id, proposal_payload}

映射为 xsyy 历史结构：
    {"version", "grade", "main_tag", "sub_tags", ...元数据字段}
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def map_agent_result(
    data: dict,
    *,
    question: str = "",
    title: str = "",
) -> dict:
    """把 agent-platform /tag-agent/recognize 响应映射为 xsyy 兼容结果.

    Returns:
        {
          "primary": {"version","grade","main_tag","sub_tags"} | None,
          "second": None,
          "_meta": {"source", "confidence", "engine": "agent", "action"},
          "knowledge_tags": {...} | None,
          "pending_tag_id": str,
          "question_proposal_id": str,
        }
    """
    outcome = data.get("outcome") if isinstance(data, dict) else None
    src = outcome or data
    if not isinstance(src, dict):
        return {
            "primary": None, "second": None,
            "_meta": {"source": "agent_invalid", "engine": "agent", "confidence": None},
            "knowledge_tags": None, "pending_tag_id": "", "question_proposal_id": "",
        }

    domain = src.get("domain", "")
    grade = src.get("grade", "")
    chapter = src.get("chapter", "")
    tag = src.get("tag", "")
    action = src.get("action", "")

    primary = None
    if domain and grade and chapter and tag:
        primary = {
            "version": domain,
            "grade": grade,
            "main_tag": chapter,
            "sub_tags": [tag],
        }

    # agent 已带的 knowledge_tags（含 tag_source / pending 状态）优先
    knowledge_tags = src.get("knowledge_tags")
    if knowledge_tags is None and primary:
        knowledge_tags = {
            "version": domain, "grade": grade, "main_tag": chapter,
            "sub_tags": [tag],
            "tag_source": "official" if action == "inject_official" else "pre_joined",
            "temporary_use": bool(action in ("create_pending_tag", "create_pending_chain", "propose_modify")),
            "pending_review_status": "pending" if knowledge_tags is None and action not in ("inject_official",) else "official",
            "created_by_agent": True,
        }

    return {
        "primary": primary,
        "second": None,
        "_meta": {
            "source": action or "agent",
            "confidence": src.get("confidence"),
            "engine": "agent",
            "action": action,
        },
        "knowledge_tags": knowledge_tags,
        "pending_tag_id": src.get("pending_tag_id", "") or data.get("pending_tag_id", ""),
        "question_proposal_id": data.get("question_proposal_id", ""),
        "question": question,
        "title": title,
    }
