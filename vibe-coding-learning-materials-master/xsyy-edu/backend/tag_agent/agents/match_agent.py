# -*- coding: utf-8 -*-
"""智能体2：章/单元 + 知识点标签匹配（方案"三.2/三.3"）.

按层级逐级匹配，不允许跳级：
- step="chapter"：在知识域+年级范围内匹配章/单元
- step="tag"：在已匹配的章/单元下匹配知识点标签
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from tag_agent.agents.base import BaseTagAgent, as_bool, as_float, as_str
from tag_agent.agent_tools import build_library_toolkit
from tag_agent.llm import create_agent
from tag_agent.prompts import (
    SYSTEM_MATCH,
    SYSTEM_MATCH_CHAPTER,
    build_chapter_match_prompt,
    build_tag_match_prompt,
)
from tag_agent.tag_library import TagLibrary

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    matched: bool
    chapter: str
    tag: str
    matched_keyword: str
    confidence: float
    reasoning: str
    raw: dict | None = None


class MatchAgent:
    """在限定范围内匹配章/单元或知识点标签."""

    def __init__(self, library: TagLibrary, timeout: float = 180.0):
        self._library = library
        # 章/单元匹配：候选少、名字清晰，保持单次调用（不背工具循环的开销，
        # 否则模型会逐章查标签，3-4 次往返直接吃满主链路 120s 识别预算）。
        self._chapter_inner = BaseTagAgent(
            create_agent("标签层级匹配智能体", SYSTEM_MATCH_CHAPTER),
            timeout,
        )
        # 知识点匹配：歧义高发，配标签库只读查询工具（真正的工具循环，
        # 模型可对拿不准的候选查关键词/定义后再判定）。
        self._inner = BaseTagAgent(
            create_agent(
                "标签层级匹配智能体",
                SYSTEM_MATCH,
                toolkit=build_library_toolkit(library),
            ),
            timeout,
        )

    async def match_chapter(self, question: str, domain: str, grade: str) -> MatchResult:
        """匹配章/单元."""
        chapters = self._library.list_chapters(domain, grade)
        if not chapters:
            return MatchResult(
                matched=False, chapter="", tag="", matched_keyword="",
                confidence=0.0, reasoning="该知识域+年级下无章/单元候选",
            )
        data = await self._chapter_inner.ask(
            build_chapter_match_prompt(question, domain, grade, chapters, self._library)
        )
        if data is None:
            return MatchResult(
                matched=False, chapter="", tag="", matched_keyword="",
                confidence=0.0, reasoning="智能体调用失败", raw=data,
            )
        chapter = as_str(data, "chapter")
        if as_bool(data, "matched") and chapter not in chapters:
            # 防止模型自创章/单元
            chapter = self._fuzzy_in(chapter, chapters)
            if chapter is None:
                return MatchResult(
                    matched=False, chapter="", tag="", matched_keyword="",
                    confidence=0.0, reasoning="模型输出了库外章/单元", raw=data,
                )
        return MatchResult(
            matched=as_bool(data, "matched") and bool(chapter),
            chapter=chapter or "",
            tag="",
            matched_keyword="",
            confidence=as_float(data, "confidence"),
            reasoning=as_str(data, "reasoning"),
            raw=data,
        )

    async def match_tag(
        self, question: str, domain: str, grade: str, chapter: str
    ) -> MatchResult:
        """在章/单元下匹配知识点标签."""
        tags = self._library.list_tags(domain, grade, chapter)
        if not tags:
            return MatchResult(
                matched=False, chapter=chapter, tag="", matched_keyword="",
                confidence=0.0, reasoning="该章/单元下无知识点标签候选",
            )
        data = await self._inner.ask(
            build_tag_match_prompt(question, domain, grade, chapter, tags, self._library)
        )
        if data is None:
            return MatchResult(
                matched=False, chapter=chapter, tag="", matched_keyword="",
                confidence=0.0, reasoning="智能体调用失败", raw=data,
            )
        tag = as_str(data, "tag")
        if as_bool(data, "matched") and tag not in tags:
            tag = self._fuzzy_in(tag, tags) or ""
        return MatchResult(
            matched=as_bool(data, "matched") and bool(tag),
            chapter=chapter,
            tag=tag,
            matched_keyword=as_str(data, "matched_keyword"),
            confidence=as_float(data, "confidence"),
            reasoning=as_str(data, "reasoning"),
            raw=data,
        )

    @staticmethod
    def _fuzzy_in(value: str, choices: list[str]) -> str | None:
        """在候选中做包含/被包含模糊匹配."""
        if not value:
            return None
        for c in choices:
            if value in c or c in value:
                return c
        return None
