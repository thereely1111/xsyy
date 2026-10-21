# -*- coding: utf-8 -*-
"""智能体5：相似标签查重校验（方案"十.3"，纯规则，不调 LLM）.

生成新标签前，必须与同知识域、同年级、同章/单元下的已有知识点标签
（以及预加入池）做相似度比对，避免重复标签。
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from tag_agent.tag_library import TagLibrary


@dataclass
class DuplicateCheckResult:
    is_duplicate: bool
    similar_tag: str
    similarity: float


def _char_jaccard(a: str, b: str) -> float:
    """基于字符集合的 Jaccard 相似度."""
    if not a or not b:
        return 0.0
    set_a, set_b = set(a), set(b)
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


class ValidateAgent:
    """查重校验器."""

    def __init__(self, library: TagLibrary, threshold: float = 0.85):
        self._library = library
        self._threshold = threshold

    def check(
        self,
        candidate: str,
        domain: str,
        grade: str,
        chapter: str,
        pending_names: list[str] | None = None,
        *,
        mode: str = "tag",
    ) -> DuplicateCheckResult:
        """与正式标签库 + 预加入池比对，判断候选是否重复.

        Args:
            mode: "tag" — 知识点标签候选，与同章/单元下的标签、章/单元名、预加入池比较；
                  "chapter" — 章/单元候选，与同知识域下所有已有章/单元、预加入池比较。
        """
        if not candidate:
            return DuplicateCheckResult(False, "", 0.0)

        candidates: list[str] = []
        if mode == "chapter":
            for g in self._library.list_grades():
                candidates.extend(self._library.list_chapters(domain, g))
        else:
            candidates.extend(self._library.list_tags(domain, grade, chapter))
            candidates.append(chapter)  # 防止知识点标签与章/单元重名
        candidates.extend(pending_names or [])

        best_name, best_score = "", 0.0
        for name in candidates:
            if not name:
                continue
            score = max(
                SequenceMatcher(None, candidate, name).ratio(),
                _char_jaccard(candidate, name),
            )
            if score > best_score:
                best_score, best_name = score, name
            if best_score >= self._threshold:
                break

        return DuplicateCheckResult(
            is_duplicate=best_score >= self._threshold,
            similar_tag=best_name,
            similarity=round(best_score, 4),
        )
