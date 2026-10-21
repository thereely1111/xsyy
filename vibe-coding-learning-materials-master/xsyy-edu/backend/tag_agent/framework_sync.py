# -*- coding: utf-8 -*-
"""正式标签库回写：审核生效后把 TagLibrary 内存库差量同步到 knowledge_tag_framework 表.

背景（2026-09-01 修复"审核通过后不同步标签表"）：
- 原实现中 promote_to_official / update_tag / delete_tag / merge_tags 只改进程内存
  （library.framework），从未写回 knowledge_tag_framework 表，导致进程重启后
  审核结果全部丢失，后台"知识标签"列表与识别器也看不到新标签。

"识别到哪个库就使用哪个库"：
- TagLibrary 从 remote_db_url（TAG_AGENT_REMOTE_DB_URL）加载 framework（source=database）
  时，回写目标就是**同一个库**（复用 tag_agent.db.get_engine()，与加载源天然一致），
  天然支持多库部署（测试库 test_xsyy / 生产库 xsyy 各自闭环，一套代码、配置驱动）。
- source=json（种子文件，未配置 remote_db_url 或远程加载失败）时跳过回写。

同步策略：**全量差量对齐**（幂等、支持"审核后修改审核"的重判回退）：
    期望集合 = 当前 library.hierarchy 展开的所有 (version, grade, main_tag, sub_tag)
             + keyword_store 合并关键词；
    表内缺失 → INSERT；keyword 不同 → UPDATE；表内存在但期望缺失 → DELETE
    （DELETE 仅限 sub_tag 非空行，避免误删章级占位行）。
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from tag_agent.tag_library import TagLibrary

logger = logging.getLogger(__name__)

_KEYWORD_MAX_LEN = 500  # knowledge_tag_framework.keyword VARCHAR(500)


def _expected_rows(library: TagLibrary) -> dict[tuple[str, str, str, str], str]:
    """从内存库构建期望状态 {(version, grade, main_tag, sub_tag): keyword}."""
    expected: dict[tuple[str, str, str, str], str] = {}
    for version, grades in (library.hierarchy or {}).items():
        for grade, chapters in grades.items():
            for main_tag, tags in chapters.items():
                for sub_tag in tags:
                    if not (version and grade and main_tag and sub_tag):
                        continue
                    kws = library.get_keywords(sub_tag) or []
                    keyword = "、".join(kws)
                    if len(keyword) > _KEYWORD_MAX_LEN:
                        keyword = keyword[:_KEYWORD_MAX_LEN]
                    expected[(version, grade, main_tag, sub_tag)] = keyword
    return expected


async def sync_library_to_framework(library: TagLibrary) -> bool:
    """把内存正式库差量写回 knowledge_tag_framework 表（识别哪个库就写哪个库）.

    Returns:
        True=已执行回写；False=标签库非 database 来源（种子），跳过。
    """
    if getattr(library, "source", "json") != "database":
        logger.info("标签库来源=%s（非远程库），跳过数据库回写", library.source)
        return False

    from tag_agent.db import get_engine  # 与 TagLibrary 加载源同一库

    expected = _expected_rows(library)

    engine = get_engine()
    inserts = updates = deletes = 0
    async with engine.begin() as conn:
        # 当前表内有效行（与加载条件一致：sub_tag 非空）
        rows = (await conn.execute(text(
            "SELECT version, grade, main_tag, sub_tag, keyword "
            "FROM knowledge_tag_framework "
            "WHERE sub_tag IS NOT NULL AND sub_tag != ''"
        ))).all()
        current: dict[tuple[str, str, str, str], str] = {
            ((r[0] or ""), (r[1] or ""), (r[2] or ""), (r[3] or "")): (r[4] or "")
            for r in rows
        }

        # INSERT / UPDATE
        for key, keyword in expected.items():
            version, grade, main_tag, sub_tag = key
            if key not in current:
                await conn.execute(text(
                    "INSERT INTO knowledge_tag_framework "
                    "(version, grade, main_tag, sub_tag, keyword, created_at) "
                    "VALUES (:version, :grade, :main_tag, :sub_tag, :keyword, NOW())"
                ), {
                    "version": version, "grade": grade,
                    "main_tag": main_tag, "sub_tag": sub_tag,
                    "keyword": keyword or None,
                })
                inserts += 1
            elif (current[key] or "") != keyword:
                await conn.execute(text(
                    "UPDATE knowledge_tag_framework SET keyword = :keyword "
                    "WHERE version = :version AND grade = :grade "
                    "AND main_tag = :main_tag AND sub_tag = :sub_tag"
                ), {
                    "version": version, "grade": grade,
                    "main_tag": main_tag, "sub_tag": sub_tag,
                    "keyword": keyword or None,
                })
                updates += 1

        # DELETE（期望集合中已不存在的有效行：被删除/合并/改名的标签）
        for key in current:
            if key not in expected:
                version, grade, main_tag, sub_tag = key
                await conn.execute(text(
                    "DELETE FROM knowledge_tag_framework "
                    "WHERE version = :version AND grade = :grade "
                    "AND main_tag = :main_tag AND sub_tag = :sub_tag"
                ), {
                    "version": version, "grade": grade,
                    "main_tag": main_tag, "sub_tag": sub_tag,
                })
                deletes += 1

    logger.info(
        "正式标签库回写完成: 新增=%s 更新=%s 删除=%s（期望共 %s 行）",
        inserts, updates, deletes, len(expected),
    )
    return True


def clear_framework_caches() -> None:
    """审核回写后清理宿主侧框架缓存，让识别器与后台立即读到最新数据."""
    try:
        from knowledge_tag_injector import reload_framework
        reload_framework()
    except Exception as e:  # noqa: BLE001
        logger.warning("知识标签注入器缓存刷新失败（不影响本次回写）: %s", e)
    try:
        from app import _clear_knowledge_framework_cache
        _clear_knowledge_framework_cache()
    except Exception as e:  # noqa: BLE001
        logger.warning("管理后台框架缓存清除失败（不影响本次回写）: %s", e)
