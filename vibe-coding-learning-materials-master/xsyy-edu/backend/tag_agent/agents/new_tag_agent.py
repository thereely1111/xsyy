# -*- coding: utf-8 -*-
"""智能体4：新标签生成（场景二/场景三，方案"五/六"）.

- 场景二：章/单元已匹配，生成预加入知识点标签 + 关键词
- 场景三：章/单元无法匹配，生成候选章/单元 + 知识点标签链路（更严格）
"""
from __future__ import annotations

from dataclasses import dataclass, field

from tag_agent.agents.base import (
    BaseTagAgent,
    as_float,
    as_list,
    as_str,
)
from tag_agent.llm import create_agent
from tag_agent.prompts import (
    SYSTEM_CHAPTER_NEW,
    SYSTEM_NEW_TAG,
    build_new_chapter_prompt,
    build_new_tag_prompt,
)
from tag_agent.tag_library import TagLibrary


@dataclass
class NewTagResult:
    tag_name: str
    keywords: list[str]
    confidence: float
    reasoning: str
    # 场景三专用
    chapter: str = ""
    no_match_reason: str = ""
    candidate_chapters: list[str] = field(default_factory=list)
    raw: dict | None = None


class NewTagAgent:
    """生成预加入标签（知识点标签或章/单元链路）."""

    def __init__(self, library: TagLibrary, timeout: float = 180.0):
        self._library = library
        self._inner = BaseTagAgent(create_agent("新标签生成智能体", SYSTEM_NEW_TAG), timeout)
        self._chapter_inner = BaseTagAgent(create_agent("章/单元生成智能体", SYSTEM_CHAPTER_NEW), timeout)

    async def run_tag(self, question: str, domain: str, grade: str, chapter: str) -> NewTagResult:
        """场景二：生成预加入知识点标签."""
        similar_tags = self._library.list_tags(domain, grade, chapter)
        data = await self._inner.ask(
            build_new_tag_prompt(question, domain, grade, chapter, similar_tags)
        )
        if data is None:
            return NewTagResult(tag_name="", keywords=[], confidence=0.0, reasoning="智能体调用失败", raw=data)
        keywords = [kw for kw in as_list(data, "keywords") if kw in question][:5]
        return NewTagResult(
            tag_name=as_str(data, "tag_name"),
            keywords=keywords,
            confidence=as_float(data, "confidence"),
            reasoning=as_str(data, "reasoning"),
            raw=data,
        )

    async def run_chapter(self, question: str, domain: str, grade: str) -> NewTagResult:
        """场景三：生成候选章/单元 + 知识点标签链路."""
        close_chapters: list[str] = []
        # 相近章/单元：取该知识域下所有年级的章/单元（用于提示模型）
        seen: set[str] = set()
        for g in self._library.list_grades():
            for c in self._library.list_chapters(domain, g):
                if c not in seen:
                    seen.add(c)
                    close_chapters.append(c)
        data = await self._chapter_inner.ask(
            build_new_chapter_prompt(question, domain, grade, close_chapters)
        )
        if data is None:
            return NewTagResult(tag_name="", keywords=[], confidence=0.0, reasoning="智能体调用失败", raw=data)
        keywords = [kw for kw in as_list(data, "keywords") if kw in question][:5]
        return NewTagResult(
            tag_name=as_str(data, "tag_name"),
            chapter=as_str(data, "chapter"),
            keywords=keywords,
            confidence=as_float(data, "confidence"),
            reasoning=as_str(data, "reasoning"),
            no_match_reason=as_str(data, "no_match_reason"),
            candidate_chapters=[c for c in as_list(data, "candidate_chapters") if c in close_chapters],
            raw=data,
        )
