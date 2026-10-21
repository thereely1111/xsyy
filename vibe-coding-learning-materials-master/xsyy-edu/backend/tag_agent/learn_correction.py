# -*- coding: utf-8 -*-
"""P1.5 标签修改学习（Label Learning from Corrections）.

管理员在「教学内容-编辑内容」保存标签更改（learn=true）后，对“变更后新增/替换到的
正式标签 B”自动提炼**可泛化的强关键词**，并对该标签的同类题库做“干跑”回验，
命中 ≥1 道同类题才算可泛化；0 命中标记“疑似过窄”，仍进审核队列但默认不勾选。
最终写入 `tag_agent_label_suggestions` 表，由管理员在 tag_review.html「标签增强建议」
标签页审核；通过即并入词库（library.add_keywords + framework_sync 回写）。

设计原则（对照方案 §9.1-B）：
- 提炼为一次轻量 LLM 调用，复用 tag_agent.llm.create_agent / agents.base.BaseTagAgent。
- 全程异步：由 app.py 的保存接口用 asyncio.create_task 后台触发，绝不阻塞标签保存主流程。
- 人工审核闭环：不通过审核绝不入库；整体可开关、可日限额。
- 只增强“判词命中”一环，不改识别模型与正常标签审核流程。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select, text

from tag_agent.config import (
    get_label_learning_daily_quota,
    get_label_learning_enabled,
    get_tag_agent_settings,
)
from tag_agent.db import get_session_factory
from tag_agent.models import LabelSuggestion
from tag_agent.tag_library import TagLibrary

logger = logging.getLogger(__name__)

# 标签 B 已有判词达到该数量则视为“词库已足够”，跳过提炼以省调用
KEYWORD_SUFFICIENT_THRESHOLD = 3
# 单次提炼候选判词数量上限
MAX_CANDIDATES = 4

_PURE_LITERAL_RE = re.compile(r"^[\d\s\+\-\*/\=\(\)\.\×\÷×÷√%]+$")


def _norm_subtags(group) -> list[str]:
    """从标签组 dict 提取 sub_tags 列表（主/第二标签组通用）."""
    if not group or not isinstance(group, dict):
        return []
    return [str(s).strip() for s in (group.get("sub_tags") or []) if str(s).strip()]


def _is_literal_keyword(kw: str) -> bool:
    """防御：剔除纯数值 / 纯算式等不可泛化字面量（1+1、35、√2 等）."""
    if not kw or len(kw) < 2:
        return True
    return bool(_PURE_LITERAL_RE.match(kw.strip()))


async def extract_strong_keywords(
    question: str,
    image_desc: str,
    old_tags: list[str],
    new_tag_b: str,
    existing_keywords: list[str],
) -> list[dict]:
    """调用一次轻量 LLM，提炼标签 B 的可泛化强关键词候选.

    Returns:
        [{"keyword": str, "reason": str}, ...]（已做字面量/长度防御过滤）
    """
    from tag_agent.agents.base import BaseTagAgent
    from tag_agent.llm import create_agent
    from tag_agent.prompts import build_learn_from_correction_prompt

    prompt = build_learn_from_correction_prompt(
        question=question,
        image_desc=image_desc or "",
        old_tags=old_tags or [],
        new_tag_b=new_tag_b,
        existing_keywords=existing_keywords or [],
    )
    try:
        agent = create_agent("标签增强建议-强关键词提炼", _LEARN_SYSTEM_PROMPT)
        base = BaseTagAgent(agent)
        result = await base.ask(prompt)
        if result is None:
            # 一次自纠重试：Agent 保留上文（含上次输出），明确要求只回 JSON 本体
            logger.warning("[标签增强] 提炼输出首次解析失败，要求模型自纠重试一次")
            result = await base.ask(
                "你上一次的输出无法解析为 JSON。请严格只输出一个 JSON 对象本体，"
                '格式：{"candidates": [{"keyword": "可泛化判词", "reason": "理由"}], '
                '"confidence": 0.0}，'
                "不要任何解释文字、前后缀或代码块标记。"
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("[标签增强] 提炼 LLM 调用失败（跳过）: %s", e)
        return []

    if not result or not isinstance(result, dict):
        return []
    raw = result.get("candidates") or []
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        kw = str(item.get("keyword") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not kw or _is_literal_keyword(kw):
            continue
        out.append({"keyword": kw, "reason": reason})
        if len(out) >= MAX_CANDIDATES:
            break
    return out


async def _dry_run_verify(keyword: str, new_tag_b: str, session) -> tuple[int, list[str]]:
    """干跑回验：用候选判词对标签 B 的同类题库（teachings）做子串命中.

    Returns:
        (hits, samples) — 命中同类题数 + 命中的题目片段（最多 2 条）。
        失败或无可查时保守返回 (0, [])，由审核人把关。
    """
    if not keyword or len(keyword) < 2:
        return 0, []
    try:
        stmt = text(
            "SELECT task_id, question FROM teachings "
            "WHERE JSON_CONTAINS(sub_tags, :tag) LIMIT 30"
        )
        rows = (await session.execute(stmt, {"tag": json.dumps(new_tag_b)})).all()
        hits = 0
        samples: list[str] = []
        for r in rows:
            q = (r.question or "") if isinstance(r.question, str) else ""
            if keyword in q:
                hits += 1
                if len(samples) < 2:
                    samples.append(q[:80])
        return hits, samples
    except Exception as e:  # noqa: BLE001
        logger.warning("[标签增强] 干跑回验失败（保守计 0 命中）: %s", e)
        return 0, []


async def schedule_label_learning(
    task_id: str,
    question_text: Optional[str],
    before: dict,
    after: dict,
    new_tags: dict,
    admin_id: str = "admin",
) -> int:
    """后台调度：检测变更到的标签 B → 提炼 → 干跑 → 写入审核队列.

    由 app.py 在标签保存接口内通过 asyncio.create_task 触发。
    返回写入的候选建议条数（0 表示跳过）。
    """
    if not get_label_learning_enabled():
        logger.info("[标签增强] 功能开关关闭，跳过")
        return 0

    before_tags = set(_norm_subtags(before.get("primary")) + _norm_subtags(before.get("second")))
    after_tags = set(_norm_subtags(after.get("primary")) + _norm_subtags(after.get("second")))
    changed_to = after_tags - before_tags
    if not changed_to:
        return 0

    settings = get_tag_agent_settings()
    # 只读加载标签库（读取 B 的既有判词 + 是否正式存在）。
    # 用 to_thread 把阻塞的 pymysql 加载移出事件循环，避免影响并发请求。
    library = await asyncio.to_thread(TagLibrary.load, settings)

    quota = get_label_learning_daily_quota()
    factory = get_session_factory()
    created = 0
    try:
        async with factory() as session:
            # ── 日限额（按今日已生成建议数）──
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            try:
                today_count = (
                    await session.execute(
                        select(func.count())
                        .select_from(LabelSuggestion)
                        .where(LabelSuggestion.created_at >= today_start)
                    )
                ).scalar() or 0
            except Exception:  # noqa: BLE001
                today_count = 0
            remaining = quota - today_count
            if remaining <= 0:
                logger.info("[标签增强] 已达日限额(%s)，跳过本次", quota)
                return 0

            # 题目文本（提案依据），未传入则从库中取
            q_text = question_text or ""
            if not q_text:
                try:
                    row = (
                        await session.execute(
                            select(Teaching.question).where(Teaching.task_id == task_id).limit(1)
                        )
                    ).first()
                    q_text = (row[0] or "") if row else ""
                except Exception:  # noqa: BLE001
                    q_text = ""

            for idx, tag_b in enumerate(sorted(changed_to)):
                if created >= remaining:
                    break
                # 仅对“正式库已存在且判词不足”的标签 B 提炼（补强冷门/新题型短板）。
                # 全新标签由既有 PendingTag 新增提案流程覆盖，不在此重复。
                if library.find_tag(tag_b) is None:
                    continue
                existing_kw = library.get_keywords(tag_b)
                if len(existing_kw) >= KEYWORD_SUFFICIENT_THRESHOLD:
                    continue

                candidates_raw = await extract_strong_keywords(
                    question=q_text,
                    image_desc="",
                    old_tags=sorted(before_tags),
                    new_tag_b=tag_b,
                    existing_keywords=existing_kw,
                )
                if not candidates_raw:
                    continue

                candidates = []
                for c in candidates_raw:
                    hits, samples = await _dry_run_verify(c["keyword"], tag_b, session)
                    candidates.append({
                        "keyword": c["keyword"],
                        "reason": c["reason"],
                        "hits": hits,
                        "hit_samples": samples,
                        "too_narrow": hits == 0,  # 0 命中同类题 → 疑似只命中本题
                    })

                # 定位标签 B 的层级上下文（用于审核展示）
                info = library.tag_info.get(tag_b) or {}
                session.add(LabelSuggestion(
                    task_id=task_id,
                    question_text=(q_text or "")[:500],
                    old_tags=sorted(before_tags),
                    new_tag=tag_b,
                    new_tag_domain=info.get("domain", ""),
                    new_tag_grade=info.get("grade", ""),
                    new_tag_chapter=info.get("chapter", ""),
                    candidates=candidates,
                    status="pending",
                    created_by=admin_id,
                ))
                created += 1
                logger.info(
                    "[标签增强] 已为标签「%s」生成 %s 条候选建议（来源题 %s）",
                    tag_b, len(candidates), task_id,
                )
            if created:
                await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("[标签增强] 后台调度异常: %s", e)
        return 0
    return created


# 复用 prompts.build_learn_from_correction_prompt 的系统提示（提炼纪律集中在此）。
# 该常量由 prompts.py.add.txt 补丁提供，合并后存在。
from tag_agent.prompts import SYSTEM_LEARN_FROM_CORRECTION as _LEARN_SYSTEM_PROMPT  # noqa: E402

# 延迟导入避免循环引用（Teaching 属业务库模型）
from database.models import Teaching  # noqa: E402
