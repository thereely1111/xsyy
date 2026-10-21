# -*- coding: utf-8 -*-
"""智能体7：重复标签检测（阶段一新增，方案「删除重复标签」能力）.

规则层（不调 LLM）全库扫描：知识点标签两两比对
（SequenceMatcher + 字符 Jaccard），相似度超过阈值即标记候选重复；
边界区间（llm_confirm_threshold ~ threshold）可调 LLM 二次确认，降低误报。

输出 DedupProposal（operation=merge / delete），仅提案、绝不直接删库，
由管理员在「预修改」审核队列确认后生效。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

from tag_agent.agents.base import (
    BaseTagAgent,
    as_bool,
    as_float,
    as_str,
)
from tag_agent.agents.validate_agent import _char_jaccard
from tag_agent.llm import create_agent
from tag_agent.prompts import (
    SYSTEM_DEDUP,
    build_dedup_confirm_prompt,
)
from tag_agent.tag_library import TagLibrary

logger = logging.getLogger(__name__)


@dataclass
class DedupProposal:
    """重复标签提案（operation=merge / delete）."""

    primary_tag: str            # 保留方（更长/更规范的名称）
    duplicate_tag: str          # 建议删除/合并方
    operation: str = "merge"    # merge | delete
    similarity: float = 0.0
    evidence: str = ""          # 判定依据（相似度 / LLM 确认）
    confidence: float = 0.0
    raw: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "operation": self.operation,
            "primary_tag": self.primary_tag,
            "duplicate_tag": self.duplicate_tag,
            "similarity": round(self.similarity, 4),
            "evidence": self.evidence,
            "confidence": round(self.confidence, 4),
        }


class DedupAgent:
    """重复标签检测：规则层全库扫描 + 可选 LLM 边界确认."""

    def __init__(
        self,
        library: TagLibrary,
        threshold: float = 0.85,
        llm_confirm_threshold: float = 0.75,
        timeout: float = 180.0,
    ):
        self._library = library
        self._threshold = threshold
        self._llm_confirm_threshold = llm_confirm_threshold
        self._confirm_inner = BaseTagAgent(
            create_agent("标签去重确认智能体", SYSTEM_DEDUP), timeout
        )

    # ── 相似度 ──────────────────────────────────────────────────────────────

    @staticmethod
    def similarity(a: str, b: str) -> float:
        """综合相似度：字符串比例 + 字符集合 Jaccard，取较大者."""
        if not a or not b:
            return 0.0
        return max(
            SequenceMatcher(None, a, b).ratio(),
            _char_jaccard(a, b),
        )

    # ── 全库扫描 ────────────────────────────────────────────────────────────

    async def scan(
        self,
        *,
        use_llm_confirm: bool = True,
        max_proposals: int = 200,
    ) -> list[DedupProposal]:
        """全库扫描，返回重复标签提案（仅提案）.

        防误报规则：
        - 跨知识域同名/近名：仅当相似度 ≥ 0.95 才标记（语义可能不同）；
        - 跨年级同名（如"圆的周长"七上/七下）：仅当相似度 ≥ 0.97 才标记
          （教材内容可能不同，默认不合并）；
        - 边界区间 [llm_confirm_threshold, threshold)：调 LLM 二次确认。
        """
        proposals: list[DedupProposal] = []
        tag_info = self._library.tag_info  # {tag: {domain, grade, chapter}}
        tags = sorted(tag_info.keys())
        n = len(tags)

        for i in range(n):
            a = tags[i]
            for j in range(i + 1, n):
                b = tags[j]
                sim = self.similarity(a, b)
                if sim < self._llm_confirm_threshold:
                    continue

                info_a, info_b = tag_info[a], tag_info[b]
                if info_a.get("domain") != info_b.get("domain") and sim < 0.95:
                    continue
                if info_a.get("grade") != info_b.get("grade") and sim < 0.97:
                    continue

                if sim >= self._threshold:
                    prop = self._build_proposal(
                        a, b, info_a, sim,
                        evidence=f"相似度 {sim:.2f}，同知识域「{info_a.get('domain')}」",
                        confidence=min(sim, 0.99),
                    )
                    proposals.append(prop)
                elif use_llm_confirm:
                    if await self._confirm_pair(a, b):
                        proposals.append(self._build_proposal(
                            a, b, info_a, sim,
                            evidence=f"LLM 确认语义重复（相似度 {sim:.2f}）",
                            confidence=0.80,
                        ))
                if len(proposals) >= max_proposals:
                    logger.warning("去重提案达到上限 %s，提前结束扫描", max_proposals)
                    return proposals
        return proposals

    # ── 内部工具 ────────────────────────────────────────────────────────────

    async def _confirm_pair(self, a: str, b: str) -> bool:
        data = await self._confirm_inner.ask(build_dedup_confirm_prompt(a, b))
        if data is None:
            logger.warning("[去重确认] LLM 调用失败，按不重复处理: %s vs %s", a, b)
            return False
        return as_bool(data, "is_duplicate")

    def _build_proposal(
        self,
        a: str,
        b: str,
        info_a: dict,
        sim: float,
        *,
        evidence: str,
        confidence: float,
    ) -> DedupProposal:
        primary, dup = self._pick_primary(a, b)
        return DedupProposal(
            primary_tag=primary,
            duplicate_tag=dup,
            operation="merge",
            similarity=sim,
            evidence=evidence,
            confidence=confidence,
            raw={"pair": (a, b), "info": info_a},
        )

    @staticmethod
    def _pick_primary(a: str, b: str) -> tuple[str, str]:
        """保留更长/更规范的名称作为 primary（短者并入长者）."""
        if len(a) >= len(b):
            return a, b
        return b, a
