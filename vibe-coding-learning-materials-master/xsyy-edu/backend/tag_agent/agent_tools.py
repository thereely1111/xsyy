# -*- coding: utf-8 -*-
"""标签库只读查询工具：把关键词/归属定义从"烤进 prompt"变成"智能体可查".

2026-09-18 路线 B：匹配智能体不再被动接受候选行旁的关键词锚定，
改为可以在判定前主动调用本工具核实（查候选标签的完整关键词、
跨章搜索同名/近义标签），实现真正的工具循环。
工具严格只读，不提供任何写方法。

注意：**不要加 `from __future__ import annotations`**——
agentscope 2.0.6 的 FunctionTool 从注解动态生成 pydantic schema 时，
字符串化注解里的 Literal 无法解析会直接抛 PydanticUserError。
"""
import json
from typing import Literal

from agentscope.tool import FunctionTool, Toolkit

from tag_agent.tag_library import TagLibrary

_MAX_TAGS = 30          # 单次返回的标签数上限（保护上下文）
_MAX_KWS = 8            # 每个标签最多展示的关键词数


def build_library_toolkit(library: TagLibrary) -> Toolkit:
    """构建带标签库查询工具的工具箱（每次调用新建，绑定当前库实例）."""

    def query_tag_library(
        query_type: Literal["chapters", "tags", "tag_detail", "search"],
        domain: str = "",
        grade: str = "",
        chapter: str = "",
        keyword: str = "",
    ) -> str:
        """查询正式标签库（只读，不做判定，不写库）。

        Args:
            query_type: 查询类型——
                chapters: 列出某知识域+年级下的全部章/单元（需 domain+grade）；
                tags: 列出某章/单元下的知识点标签及其关键词（需 domain+grade+chapter）；
                tag_detail: 查单个知识点标签的完整归属与关键词（keyword=标签名）；
                search: 按名称模糊搜索知识点标签（keyword=子串，可用 domain/grade 过滤）。
            domain: 知识域（如：数与代数）
            grade: 年级（如：七上）
            chapter: 章/单元名
            keyword: 标签名或搜索子串
        """
        try:
            if query_type == "chapters":
                if not (domain and grade):
                    return json.dumps({"error": "chapters 查询需要 domain 和 grade"}, ensure_ascii=False)
                chapters = library.list_chapters(domain, grade)
                return json.dumps({"domain": domain, "grade": grade, "chapters": chapters}, ensure_ascii=False)

            if query_type == "tags":
                if not (domain and grade and chapter):
                    return json.dumps({"error": "tags 查询需要 domain、grade 和 chapter"}, ensure_ascii=False)
                tags = library.list_tags(domain, grade, chapter)[:_MAX_TAGS]
                items = [
                    {"tag": t, "keywords": library.get_keywords(t)[:_MAX_KWS]}
                    for t in tags
                ]
                return json.dumps(
                    {"domain": domain, "grade": grade, "chapter": chapter,
                     "total": len(library.list_tags(domain, grade, chapter)),
                     "returned": len(items), "tags": items},
                    ensure_ascii=False,
                )

            if query_type == "tag_detail":
                if not keyword:
                    return json.dumps({"error": "tag_detail 查询需要 keyword=标签名"}, ensure_ascii=False)
                info = library.find_tag(keyword)
                if info is None:
                    return json.dumps({"error": f"标签库中不存在：{keyword}"}, ensure_ascii=False)
                return json.dumps(
                    {"tag": keyword, **info, "keywords": library.get_keywords(keyword)[:_MAX_KWS]},
                    ensure_ascii=False,
                )

            if query_type == "search":
                if not keyword:
                    return json.dumps({"error": "search 查询需要 keyword=搜索子串"}, ensure_ascii=False)
                hits = []
                for tag, info in library.tag_info.items():
                    if keyword in tag:
                        if domain and info.get("domain") != domain:
                            continue
                        if grade and info.get("grade") != grade:
                            continue
                        hits.append({
                            "tag": tag,
                            "domain": info.get("domain", ""),
                            "grade": info.get("grade", ""),
                            "chapter": info.get("chapter", ""),
                            "keywords": library.get_keywords(tag)[:_MAX_KWS],
                        })
                        if len(hits) >= _MAX_TAGS:
                            break
                return json.dumps({"keyword": keyword, "matched": len(hits), "tags": hits}, ensure_ascii=False)

            return json.dumps({"error": f"未知 query_type：{query_type}"}, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            return json.dumps({"error": f"查询失败：{e}"}, ensure_ascii=False)

    # Toolkit 构造函数同步注册工具（add_tool 是异步方法，无法在同步 __init__ 里用）
    toolkit = Toolkit(tools=[FunctionTool(
        query_tag_library,
        name="query_tag_library",
        description="查询正式标签库（只读）：可查章/单元列表、某章下的标签及关键词、单个标签的归属详情、按名称模糊搜索。判定有歧义时先查再答。",
        is_read_only=True,
    )])
    return toolkit
