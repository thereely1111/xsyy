# -*- coding: utf-8 -*-
"""智能体3：关键词提取（场景一，方案"四"）."""
from __future__ import annotations

from dataclasses import dataclass

from tag_agent.agents.base import (
    BaseTagAgent,
    as_float,
    as_list,
    as_str,
)
from tag_agent.llm import create_agent
from tag_agent.prompts import (
    SYSTEM_KEYWORD_EXTRACT,
    build_keyword_extract_prompt,
)


@dataclass
class KeywordResult:
    keywords: list[str]
    confidence: float
    reasoning: str
    raw: dict | None = None


class KeywordExtractAgent:
    """场景一：从题目中提取 3-5 个强特征关键词（不生成标签）."""

    def __init__(self, timeout: float = 180.0):
        self._inner = BaseTagAgent(create_agent("关键词提取智能体", SYSTEM_KEYWORD_EXTRACT), timeout)

    async def run(self, question: str, tag: str) -> KeywordResult:
        data = await self._inner.ask(build_keyword_extract_prompt(question, tag))
        if data is None:
            return KeywordResult(keywords=[], confidence=0.0, reasoning="智能体调用失败", raw=data)
        keywords = as_list(data, "keywords")
        # 校验：关键词必须来自题目文本（方案"四.3.1"）
        keywords = [kw for kw in keywords if kw and kw in question]
        # 去除纯数字与过短/过长词
        keywords = [
            kw for kw in keywords
            if not kw.isdigit() and 2 <= len(kw) <= 12
        ][:5]
        return KeywordResult(
            keywords=keywords,
            confidence=as_float(data, "confidence"),
            reasoning=as_str(data, "reasoning"),
            raw=data,
        )
