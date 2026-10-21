# -*- coding: utf-8 -*-
"""智能体6：标签纠错提案（阶段一新增，方案「自动纠错标签」能力）.

输入：题目 + 已匹配的正式标签（含关键词）+ 可选修正线索
输出：CorrectionProposal（operation=modify，字段级修改提案）

仅提案、绝不直接改库——由管理员在「预修改」审核队列确认后生效。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from tag_agent.agents.base import (
    BaseTagAgent,
    as_bool,
    as_float,
    as_str,
)
from tag_agent.llm import create_agent
from tag_agent.prompts import (
    SYSTEM_CORRECTION,
    build_correction_prompt,
)
from tag_agent.tag_library import TagLibrary

logger = logging.getLogger(__name__)

# 允许修改的字段（一次只提 1 个）
VALID_FIELDS = ("keywords", "grade", "domain", "chapter", "tag_name")


@dataclass
class CorrectionProposal:
    """标签修改提案（operation=modify）."""

    can_propose: bool = False
    field: str = ""               # keywords | grade | domain | chapter | tag_name
    after: object = None          # 修改后的目标值（str 或 list[str]）
    reason: str = ""
    confidence: float = 0.0
    # 目标标签定位（编排器带入）
    target_domain: str = ""
    target_grade: str = ""
    target_chapter: str = ""
    target_tag: str = ""
    before: object = None         # 修改前快照（编排器组装）
    raw: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "operation": "modify",
            "field": self.field,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "target": {
                "domain": self.target_domain,
                "grade": self.target_grade,
                "chapter": self.target_chapter,
                "tag": self.target_tag,
            },
            "can_propose": self.can_propose,
        }


class CorrectionAgent:
    """纠错提案智能体：评估已有标签对题目的适用性，产出修改提案."""

    def __init__(self, library: TagLibrary, timeout: float = 180.0):
        self._library = library
        self._inner = BaseTagAgent(create_agent("标签纠错提案智能体", SYSTEM_CORRECTION), timeout)

    async def propose(
        self,
        question: str,
        *,
        domain: str,
        grade: str,
        chapter: str,
        tag: str,
        hint: str = "",
    ) -> CorrectionProposal:
        """对已匹配标签提出修改建议（仅提案）."""
        existing = self._library.get_keywords(tag)
        data = await self._inner.ask(
            build_correction_prompt(
                question,
                domain=domain,
                grade=grade,
                chapter=chapter,
                tag=tag,
                existing_keywords=existing,
                hint=hint,
            )
        )
        if data is None:
            return CorrectionProposal(reason="智能体调用失败", raw=data)

        prop = CorrectionProposal(
            can_propose=as_bool(data, "can_propose"),
            field=as_str(data, "field"),
            after=data.get("after"),
            reason=as_str(data, "reason"),
            confidence=as_float(data, "confidence"),
            target_domain=domain,
            target_grade=grade,
            target_chapter=chapter,
            target_tag=tag,
            raw=data,
        )
        # 硬校验：field 合法 + after 非空，否则降级为不提案（防止非法提案污染审核队列）
        if prop.can_propose and (
            prop.field not in VALID_FIELDS or not self._nonempty(prop.after)
        ):
            logger.warning("[纠错提案] 字段非法已拦截: %s", data)
            prop.can_propose = False
            prop.reason = "提案字段非法，已拦截"
        return prop

    @staticmethod
    def _nonempty(v: object) -> bool:
        if isinstance(v, (list, tuple, set)):
            return len(v) > 0
        if isinstance(v, str):
            return bool(v.strip())
        return v is not None
