# -*- coding: utf-8 -*-
"""智能体1：知识域 + 年级识别（方案"三.1"）."""
from __future__ import annotations

from dataclasses import dataclass

from tag_agent.agents.base import BaseTagAgent, as_bool, as_float, as_str
from tag_agent.llm import create_agent
from tag_agent.prompts import (
    SYSTEM_DOMAIN_GRADE,
    build_domain_grade_prompt,
)
from tag_agent.tag_library import TagLibrary


@dataclass
class DomainGradeResult:
    is_math_problem: bool
    domain: str
    grade: str
    confidence: float
    reasoning: str
    raw: dict | None = None


class DomainGradeAgent:
    """第一步：判定题目是否为数学题，并识别知识域与年级."""

    def __init__(self, library: TagLibrary, timeout: float = 180.0):
        self._library = library
        self._inner = BaseTagAgent(create_agent("知识域年级识别智能体", SYSTEM_DOMAIN_GRADE), timeout)

    async def run(self, question: str) -> DomainGradeResult:
        data = await self._inner.ask(build_domain_grade_prompt(question, self._library))
        if data is None:
            return DomainGradeResult(
                is_math_problem=False, domain="", grade="",
                confidence=0.0, reasoning="智能体调用失败", raw=data,
            )
        result = DomainGradeResult(
            is_math_problem=as_bool(data, "is_math_problem", True),
            domain=as_str(data, "domain"),
            grade=as_str(data, "grade"),
            confidence=as_float(data, "confidence"),
            reasoning=as_str(data, "reasoning"),
            raw=data,
        )
        # 归一化：确保知识域/年级在标准列表中
        result.domain = self._normalize_choice(result.domain, self._library.list_domains())
        result.grade = self._normalize_choice(result.grade, self._library.list_grades())
        return result

    @staticmethod
    def _normalize_choice(value: str, choices: list[str]) -> str:
        if not value or not choices:
            return ""
        if value in choices:
            return value
        for c in choices:
            if value in c or c in value:
                return c
        return ""
