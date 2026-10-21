# -*- coding: utf-8 -*-
"""年级 / 章节知识库（KB）只读检索核心。

维度沿用既有口径：**知识域 + 年级 + 章节**（不含教材版本维度）。

- 知识域 = 标签框架 hierarchy 的第一层（数与式 / 方程与不等式 / 函数 / 图形与几何 / 统计与概率），
  对应既有检索实现里的 `version` 字段（此处对外一律称 `domain`）。
- 年级   = hierarchy 第二层（六上 … 九下）。
- 章节   = hierarchy 第三层（main_tag，如「整式的加减」）。
- 小节   = 命中到的知识点标签（sub_tag，如「单项式与多项式」）。

检索实现**复用** `backend/knowledge_tag_rag.TagIndex`（纯标准库零依赖，与标签智能体同源算法，
不另建第二份标签树、也不另写第二套打分），本模块只做：索引加载 / 维度映射 / 学段过滤。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

KB_DIR = Path(__file__).resolve().parent
BACKEND_DIR = KB_DIR.parent
DEFAULT_INDEX = KB_DIR / "index" / "tag_index.json"
DEFAULT_CHAPTERS = KB_DIR / "index" / "chapters.json"

# 学段 → 年级集合（stage 过滤用；schema 的 stage 只有 primary / junior_high）
STAGE_GRADES: Dict[str, List[str]] = {
    "primary": ["一上", "一下", "二上", "二下", "三上", "三下",
                "四上", "四下", "五上", "五下", "六上", "六下"],
    "junior_high": ["七上", "七下", "八上", "八下", "九上", "九下"],
}

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from knowledge_tag_rag import TagIndex, keyword_hit_score  # noqa: E402  零第三方依赖（仅标准库）

# 轻量证据加权（**初值**，需黄金集标定）：字符 n-gram 余弦分数尺度低（0.05~0.3），
# 单靠分数无法区分对错，故叠加两路「字符证据」（与 knowledge_tag_rag 同思路）：
#   1) 强特征关键词命中题面（知识库自带 keyword 字段）；
#   2) 章节名直命中题面（≥3 字，人工命名的强信号）。
W_KW = 0.40
W_CHAPTER = 0.30
KW_NORM_DIV = 6.0
CHAPTER_MIN_LEN = 3


def load_index(index_path: Optional[str] = None) -> TagIndex:
    """加载离线索引（由 scripts/build_index.py 产出），并在内存重建检索结构。

    索引文件只存知识点行（domain/grade/chapter/section/keyword），倒排表在内存重建：
    千级文档耗时仅毫秒级，同时绕开 `TagIndex.load()` 词法分支的下标类型缺陷（未改 xsyy 代码）。
    """
    path = Path(index_path) if index_path else DEFAULT_INDEX
    if not path.exists():
        raise FileNotFoundError(
            f"KB 索引不存在：{path}；请先运行 scripts/build_index.py 构建"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("docs") or []
    if not rows:
        raise ValueError(f"KB 索引为空：{path}")

    index = TagIndex(backend="lexical")
    index.build([
        {
            "version": row.get("domain", ""),
            "grade": row.get("grade", ""),
            "main_tag": row.get("chapter", ""),
            "sub_tag": row.get("section", ""),
            "keyword": row.get("keyword", "") or "",
        }
        for row in rows
    ])
    return index


def load_chapters(chapters_path: Optional[str] = None) -> dict:
    """加载章节清单（domain → grade → [chapter]），用于快速列章 / 体检。"""
    path = Path(chapters_path) if chapters_path else DEFAULT_CHAPTERS
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _rerank(hits: List[dict], question: str) -> List[dict]:
    """字符证据加权重排：向量分 + 关键词命中 + 章名直命中。"""
    out = []
    for hit in hits:
        kw_hit = min(1.0, keyword_hit_score(hit.get("keyword", ""), question) / KW_NORM_DIV)
        chapter = hit.get("main_tag", "") or ""
        chapter_hit = bool(len(chapter) >= CHAPTER_MIN_LEN and chapter in question)
        score = float(hit.get("score", 0.0)) + W_KW * kw_hit + W_CHAPTER * chapter_hit
        out.append(dict(hit, score=min(1.0, score), kw_hit=kw_hit > 0, chapter_hit=chapter_hit))
    out.sort(key=lambda h: h["score"], reverse=True)
    return out


def _map_hit(hit: dict) -> dict:
    """把 TagIndex 命中项映射为 KB 维度命名。"""
    return {
        "domain": hit.get("version", ""),
        "grade": hit.get("grade", ""),
        "chapter": hit.get("main_tag", ""),
        "section": hit.get("sub_tag", ""),
        "score": round(float(hit.get("score", 0.0)), 4),
        "keyword": hit.get("keyword", ""),
        "kw_hit": bool(hit.get("kw_hit", False)),
        "chapter_hit": bool(hit.get("chapter_hit", False)),
    }


def search(index: TagIndex, question: str, domain: Optional[str] = None,
           grade: Optional[str] = None, stage: Optional[str] = None,
           top_k: int = 10) -> List[dict]:
    """按题面检索年级 / 章节。

    过滤优先级：`grade`（精确年级）> `stage`（学段，展开为年级集合逐个检索后合并）。
    两个都不给时全局检索。返回按 score 降序的命中列表（含 domain/grade/chapter/section）。
    """
    question = (question or "").strip()
    if not question:
        return []

    if grade:
        raw = index.search(question, top_k=top_k, domain=domain, grade=grade)
    elif stage:
        grades = STAGE_GRADES.get(stage, [])
        if not grades:
            return []
        merged: Dict[tuple, dict] = {}
        for g in grades:
            for h in index.search(question, top_k=top_k, domain=domain, grade=g):
                key = (h.get("version"), h.get("grade"), h.get("main_tag"), h.get("sub_tag"))
                if key not in merged or h["score"] > merged[key]["score"]:
                    merged[key] = h
        raw = list(merged.values())
    else:
        raw = index.search(question, top_k=top_k, domain=domain)

    return [_map_hit(h) for h in _rerank(raw, question)[:top_k]]