# -*- coding: utf-8 -*-
"""P3 相似题动画智能复用（Reusable Skeleton + ReuseMatchAgent，方案 §10）.

核心：新题生成动画前，先过「同法异数」判定闸门——
  ① 向量召回相似题（query_similar_teachings）
  ② 硬过滤：学段/知识域/章/标签 与本题 ContentProfile 一致才进候选
  ③ 同构判定（一次轻量 LLM）：输出 is_same_method / template_task_id /
     method_signature / slot_map / confidence
  ④ 阈值闸门：
       confidence ≥ 自动阈值 且 REUSE_AUTO_APPLY=true → 直接复用渲染（跳过生成，省算力）
       手动阈值 ≤ confidence < 自动阈值       → 写「复用建议队列」人工确认
       < 手动阈值                              → 记一次“复用未命中”（命中率分母），走正常生成
  ⑤ 命中后懒抽取骨架（模板题无 skeleton 时，按产物自动抽取一次并缓存）+ 渲染复用产物

设计原则（对照方案 §10 + 复用 P1.5 范式）：
- 同构判定 / 骨架抽取 / 题型沉淀 均为轻量 LLM 调用，复用 create_agent / BaseTagAgent。
- 全程异步、开关可控、异常 fail-open：复用判定失败绝不影响正常生成。
- 人工审核闭环：复用建议/题型提示词不通过审核绝不落地；整体可开关、可阈值。
- 复用产物写 reuse_info 溯源；渲染后校验“无残留 {{slot}}”兜底，失败降级 L2。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select, text

from tag_agent.config import (
    get_reuse_auto_apply,
    get_reuse_auto_threshold,
    get_reuse_enabled,
    get_reuse_image_enabled,
    get_reuse_manual_threshold,
    get_reuse_sediment_threshold,
    get_tag_agent_settings,
)
from tag_agent.db import get_session_factory
from tag_agent.models import PatternSuggestion, ReuseSuggestion, ReuseStat, ReuseSuggestionStatus

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = ROOT / "storage"

# 复用闸门硬过滤最少命中的标签维度（学段/知识域/章/标签 中至少命中数）
HARD_FILTER_MIN_DIMS = 2
# 单次同构判定候选上限（已按相似度排过序）
MAX_ISO_CANDIDATES = 5
# 自动复用（跳过生成）总开关 env：REUSE_AUTO_APPLY（默认 false，先灰度人工确认）
# 占位符正则：{{ s_v1 }} / {{s_dist}}
_SLOT_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


# ───────────────────────────── 工具 ─────────────────────────────

def _task_dir(task_id: str) -> Path:
    return STORAGE_DIR / task_id


def _read_teaching_data(task_id: str) -> Optional[dict]:
    """读取某题的 teaching_data.json（不存在返回 None）."""
    p = _task_dir(task_id) / "teaching_data.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 读取 teaching_data.json 失败 %s: %s", task_id, e)
        return None


def _write_teaching_data(task_id: str, data: dict) -> bool:
    """原子写 teaching_data.json（沿用 pipeline 的 tmp + replace 原子写法）."""
    p = _task_dir(task_id) / "teaching_data.json"
    tmp = p.with_name(p.name + ".tmp")
    for _ in range(5):
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            p.replace(tmp)
            return True
        except OSError:
            import time
            time.sleep(0.5)
    return False


def _read_metadata(task_id: str) -> Optional[dict]:
    p = _task_dir(task_id) / "metadata.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _write_metadata(task_id: str, meta: dict) -> None:
    p = _task_dir(task_id) / "metadata.json"
    tmp = p.with_name(p.name + ".tmp")
    for _ in range(5):
        try:
            tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            p.replace(tmp)
            return
        except OSError:
            import time
            time.sleep(0.5)


def _render_template(template_str: str, slot_map: list[dict]) -> str:
    """纯占位符替换：把 {{slot}} 换成 slot_map 中对应的 new_value（named slot，避免数值碰撞）."""
    if not template_str:
        return template_str
    lut = {str(s.get("slot")): str(s.get("new_value", "")) for s in (slot_map or []) if s.get("slot")}
    def _sub(m):
        key = m.group(1)
        return lut.get(key, m.group(0))  # 未提供映射则保留原占位符（后续校验会判失败）
    return _SLOT_RE.sub(_sub, template_str)


def _residual_slots(rendered: str) -> list[str]:
    return sorted(set(_SLOT_RE.findall(rendered or "")))


# ───────────────────────────── 召回 + 硬过滤 ─────────────────────────────

async def _get_query_embedding(question_text: str) -> Optional[list]:
    try:
        from utils.embedding_utils import get_question_embedding_async
        return await get_question_embedding_async(question_text)
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 计算题目 embedding 失败（跳过召回）: %s", e)
        return None


def _profile_dims(content_profile: Optional[dict]) -> dict:
    """从 ContentProfile 抽取硬过滤维度."""
    cp = content_profile or {}
    return {
        "stage": (cp.get("stage") or "").strip(),
        "domain": (cp.get("display_class") or cp.get("domain") or "").strip(),
        "chapter": (cp.get("chapter") or cp.get("main_tag") or "").strip(),
        "tags": set(str(t).strip() for t in (cp.get("sub_tags") or []) if str(t).strip()),
    }


def _hard_filter(candidates: list, dims: dict) -> list:
    """硬过滤：学段/知识域/章/标签 与本题一致才进候选（维度命中数 ≥ HARD_FILTER_MIN_DIMS）."""
    out = []
    for c in candidates:
        meta = (c.get("metadata") or {}) if isinstance(c, dict) else {}
        kt = meta.get("knowledge_tags") or {}
        if isinstance(kt, str):
            try:
                kt = json.loads(kt)
            except Exception:  # noqa: BLE001
                kt = {}
        kt = kt if isinstance(kt, dict) else {}
        c_stage = str(kt.get("version") or "").strip()
        c_domain = str(kt.get("domain") or kt.get("display_class") or "").strip()
        c_chapter = str(kt.get("main_tag") or kt.get("chapter") or "").strip()
        c_tags = set(str(t).strip() for t in (kt.get("sub_tags") or []) if str(t).strip())
        hits = 0
        if dims["stage"] and c_stage and dims["stage"] == c_stage:
            hits += 1
        if dims["domain"] and c_domain and dims["domain"] == c_domain:
            hits += 1
        if dims["chapter"] and c_chapter and dims["chapter"] == c_chapter:
            hits += 1
        if dims["tags"] and c_tags and (dims["tags"] & c_tags):
            hits += 1
        if hits >= HARD_FILTER_MIN_DIMS:
            out.append(c)
    return out


async def _recall_and_filter(
    question_text: str, content_profile: Optional[dict], task_id: str,
) -> list:
    try:
        from utils.vector_db import query_similar_teachings
        emb = await _get_query_embedding(question_text)
        if not emb:
            return []
        raw = query_similar_teachings(emb, n_results=10, exclude_ids=[task_id])
        dims = _profile_dims(content_profile)
        return _hard_filter(raw, dims)
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 召回+硬过滤失败（跳过）: %s", e)
        return []


# ───────────────────────────── 同构判定 ─────────────────────────────

async def _iso_judge(candidates: list, question_text: str, content_profile: Optional[dict]) -> Optional[dict]:
    """一次轻量 LLM 同构判定：返回 {is_same_method, template_task_id, method_signature, slot_map, confidence, reason}."""
    from tag_agent.agents.base import BaseTagAgent
    from tag_agent.llm import create_agent
    from tag_agent.prompts import SYSTEM_REUSE_MATCH, build_reuse_match_prompt

    # 构造候选摘要（带槽语义，优先复用既有骨架）
    cands = []
    for c in candidates[:MAX_ISO_CANDIDATES]:
        tid = c.get("id")
        td = _read_teaching_data(tid) or {}
        skel = td.get("reusable_skeleton") or {}
        cands.append({
            "task_id": tid,
            "question": (c.get("document") or "")[:200],
            "method_signature": skel.get("method_signature", ""),
            "slot_labels": [s.get("label") for s in (skel.get("slots") or [])],
        })

    prompt = build_reuse_match_prompt(
        question=question_text[:400],
        content_profile=content_profile or {},
        candidates=cands,
    )
    try:
        agent = create_agent("相似题同构判定", SYSTEM_REUSE_MATCH)
        result = await BaseTagAgent(agent).ask(prompt)
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 同构判定 LLM 失败（降级 L2）: %s", e)
        return None
    if not isinstance(result, dict):
        return None
    return result


# ───────────────────────────── 骨架：懒抽取 + 渲染 ─────────────────────────────

async def extract_skeleton(template_task_id: str) -> Optional[dict]:
    """懒抽取模板题骨架：若已有 reusable_skeleton 直接返回；否则 LLM 抽取并缓存回 teaching_data.json."""
    td = _read_teaching_data(template_task_id)
    if not td:
        return None
    skel = td.get("reusable_skeleton")
    if isinstance(skel, dict) and skel.get("scene_template"):
        return skel

    from tag_agent.agents.base import BaseTagAgent
    from tag_agent.llm import create_agent
    from tag_agent.prompts import SYSTEM_SKELETON_EXTRACT, build_skeleton_extract_prompt

    prompt = build_skeleton_extract_prompt(td)
    try:
        agent = create_agent("复用骨架抽取", SYSTEM_SKELETON_EXTRACT)
        result = await BaseTagAgent(agent).ask(prompt)
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 骨架抽取 LLM 失败（降级 L2）: %s", e)
        return None
    if not isinstance(result, dict) or not result.get("scene_template"):
        return None
    skel = {
        "method_signature": result.get("method_signature", ""),
        "slots": result.get("slots") or [],
        "scene_template": result.get("scene_template", ""),
        "steps_template": result.get("steps_template") or [],
        "layout_params": result.get("layout_params") or {},
        "gen_meta": {"model": "skeleton-extract", "version": 1},
    }
    # 缓存回模板题（不破坏原产物其它字段）
    try:
        td["reusable_skeleton"] = skel
        _write_teaching_data(template_task_id, td)
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 骨架缓存写回失败（可忽略）: %s", e)
    return skel


async def render_reuse(
    decision: dict, target_task_id: str, question_text: str, title: str, user_id: str,
) -> Optional[dict]:
    """用模板骨架 + slot_map 渲染复用产物，写入目标题 task_dir，返回新 teaching_data（失败返回 None 降级 L2）.

    复用产物写 reuse_info 溯源；渲染后校验“无残留 {{slot}}”，否则判失败。
    """
    template_task_id = decision.get("template_task_id")
    if not template_task_id:
        return None
    skel = await extract_skeleton(template_task_id)
    if not skel or not skel.get("scene_template"):
        logger.info("[复用] 模板 %s 无可用骨架，降级 L2", template_task_id)
        return None
    slot_map = decision.get("slot_map") or []

    new_scene = _render_template(skel.get("scene_template", ""), slot_map)
    new_steps = []
    for step in (skel.get("steps_template") or []):
        if not isinstance(step, dict):
            new_steps.append(step)
            continue
        ns = dict(step)
        for k in ("title", "description", "bubbleText", "arrowTarget"):
            if isinstance(ns.get(k), str):
                ns[k] = _render_template(ns[k], slot_map)
        new_steps.append(ns)

    residual = _residual_slots(new_scene) + _residual_slots(json.dumps(new_steps, ensure_ascii=False))
    if residual:
        logger.warning("[复用] 渲染后残留占位符 %s，降级 L2", residual)
        return None

    template_td = _read_teaching_data(template_task_id) or {}
    new_td = dict(template_td)
    new_td["scene_svg"] = new_scene
    new_td["steps_json"] = new_steps
    # 题干/标题用新题
    if question_text:
        new_td["question"] = question_text
    if title:
        new_td["title"] = title
    new_td["reusable_skeleton"] = skel  # 让目标题也成为未来模板
    new_td["reuse_info"] = {
        "source_task_id": template_task_id,
        "mode": decision.get("mode", "L1"),
        "confidence": float(decision.get("confidence") or 0),
        "method_signature": decision.get("method_signature", ""),
        "slot_map": slot_map,
        "generated_by": "reuse_renderer",
        "reused_at": datetime.utcnow().isoformat(),
    }
    if not _write_teaching_data(target_task_id, new_td):
        return None
    # 同步写 metadata.json 的 reuse_info（前端角标读取）
    try:
        meta = _read_metadata(target_task_id) or {}
        meta["reuse_info"] = new_td["reuse_info"]
        if question_text:
            meta["question"] = question_text
        if title:
            meta["title"] = title
        _write_metadata(target_task_id, meta)
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] metadata 复用标记写回失败（可忽略）: %s", e)

    await _record_reuse_result(decision.get("method_signature", ""), template_task_id, success=True)
    await _maybe_sediment_pattern(decision.get("method_signature", ""), template_task_id)
    return new_td


# ───────────────────────────── 统计 + 题型沉淀 ─────────────────────────────

async def _record_reuse_opportunity() -> None:
    """记录一次复用机会（用于命中率分母；仅计数，不写 DB 以免膨胀，改用 reuse_stats 汇总表在审核时累计）。"""
    # 机会计数在审核/渲染时随 method_signature 汇总，这里留空实现（命中率 = 成功 / (成功 + 未命中)）。
    # 未命中计数在 match 阶段记录到 reuse_stats 的 miss 列（见 _record_reuse_miss）。
    return


async def _record_reuse_miss(method_signature: str) -> None:
    """记录一次“可复用但未复用”（未命中 / 置信不足），用于命中率分母."""
    if not method_signature:
        return
    factory = get_session_factory()
    try:
        async with factory() as session:
            stat = (await session.execute(
                select(ReuseStat).where(ReuseStat.method_signature == method_signature)
            )).scalar_one_or_none()
            if stat is None:
                stat = ReuseStat(method_signature=method_signature, template_task_id="", reuse_count=0)
                session.add(stat)
            stat.reuse_count = (stat.reuse_count or 0) + 1
            stat.last_reuse_at = datetime.utcnow()
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] miss 统计失败（可忽略）: %s", e)


async def _record_reuse_result(method_signature: str, template_task_id: str, *, success: bool) -> None:
    """复用成功 → 累计成功次数；并检查题型沉淀阈值."""
    if not method_signature:
        return
    factory = get_session_factory()
    try:
        async with factory() as session:
            stat = (await session.execute(
                select(ReuseStat).where(ReuseStat.method_signature == method_signature)
            )).scalar_one_or_none()
            if stat is None:
                stat = ReuseStat(method_signature=method_signature, template_task_id=template_task_id)
                session.add(stat)
            if success:
                stat.success_count = (stat.success_count or 0) + 1
            stat.reuse_count = (stat.reuse_count or 0) + 1
            if template_task_id:
                stat.template_task_id = template_task_id
            stat.last_reuse_at = datetime.utcnow()
            await session.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 结果统计失败（可忽略）: %s", e)


async def _maybe_sediment_pattern(method_signature: str, template_task_id: str) -> Optional[str]:
    """§10.9 题型沉淀：同 method_signature 成功复用 ≥ 阈值 → 生成题型提示词草稿入审核队列."""
    if not method_signature:
        return None
    threshold = get_reuse_sediment_threshold()
    factory = get_session_factory()
    try:
        async with factory() as session:
            stat = (await session.execute(
                select(ReuseStat).where(ReuseStat.method_signature == method_signature)
            )).scalar_one_or_none()
            if stat is None or (stat.success_count or 0) < threshold:
                return None
            if stat.pattern_sedimented:
                return None
            # 已达标：生成草稿（一次 LLM 调用），写入 pattern_suggestions 队列
            draft = await _build_pattern_draft(method_signature, template_task_id)
            if not draft:
                return None
            sug = PatternSuggestion(
                method_signature=method_signature,
                draft_markdown=draft.get("markdown", ""),
                question_type_hint=draft.get("question_type_hint", ""),
                source_task_id=template_task_id,
                status="pending",
                created_by="reuse_engine",
            )
            session.add(sug)
            stat.pattern_sedimented = True
            await session.commit()
            logger.info("[复用] 题型提示词草稿已入队（%s）", method_signature)
            return sug.id
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 题型沉淀失败（可忽略）: %s", e)
        return None


async def _build_pattern_draft(method_signature: str, template_task_id: str) -> Optional[dict]:
    """生成题型提示词草稿（对齐 scene_patterns/50_pattern_{key}.md 结构，数据用占位符，禁抄原题数字）."""
    from tag_agent.agents.base import BaseTagAgent
    from tag_agent.llm import create_agent
    from tag_agent.prompts import SYSTEM_PATTERN_DRAFT, build_pattern_draft_prompt

    td = _read_teaching_data(template_task_id)
    if not td:
        return None
    prompt = build_pattern_draft_prompt(method_signature, td)
    try:
        agent = create_agent("题型提示词沉淀", SYSTEM_PATTERN_DRAFT)
        result = await BaseTagAgent(agent).ask(prompt)
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 题型提示词草稿 LLM 失败: %s", e)
        return None
    if isinstance(result, dict) and result.get("markdown"):
        return result
    return None


# ───────────────────────────── 闸门入口（被 pipeline / app 调用）─────────────────────────────

async def match_reuse_before_generation(
    question_text: str, title: str, content_profile: Optional[dict], task_id: str, user_id: str,
) -> Optional[dict]:
    """生成动画前的复用闸门（被 pipeline 调用）。

    - 返回 None 表示走正常生成（L2 / 未命中）；
    - 返回 dict(mode="L1", ...) 表示命中（已写入「复用建议队列」人工确认；若开启自动复用，调用方应再调 render_reuse 早退）。
    """
    if not get_reuse_enabled():
        return None
    candidates = await _recall_and_filter(question_text, content_profile, task_id)
    if not candidates:
        return None
    decision = await _iso_judge(candidates, question_text, content_profile)
    if not decision or not decision.get("is_same_method"):
        # 未命中：记一次“可复用但未复用”，用于命中率分母
        await _record_reuse_miss(decision.get("method_signature", "") if isinstance(decision, dict) else "")
        return None

    conf = float(decision.get("confidence") or 0)
    manual = get_reuse_manual_threshold()
    if conf < manual:
        await _record_reuse_miss(decision.get("method_signature", ""))
        return None

    # 命中：写「复用建议队列」（人工确认），正常生成仍进行
    decision["mode"] = "L1"
    await _write_reuse_suggestion(decision, task_id, question_text, title, user_id)
    return decision


async def _write_reuse_suggestion(
    decision: dict, task_id: str, question_text: str, title: str, user_id: str,
) -> None:
    """写一条复用建议到审核队列."""
    factory = get_session_factory()
    try:
        async with factory() as session:
            template_td = _read_teaching_data(decision.get("template_task_id") or "") or {}
            sug = ReuseSuggestion(
                task_id=task_id,
                question_text=(question_text or "")[:500],
                title=(title or "")[:255],
                template_task_id=decision.get("template_task_id", ""),
                template_title=(template_td.get("title") or "")[:255],
                method_signature=decision.get("method_signature", ""),
                confidence=float(decision.get("confidence") or 0),
                mode="L1",
                slot_map=decision.get("slot_map") or [],
                reason=decision.get("reason", ""),
                status=ReuseSuggestionStatus.PENDING,
                created_by=user_id or "system",
            )
            session.add(sug)
            await session.commit()
            logger.info(
                "[复用] 已写入复用建议（新题 %s → 模板 %s，置信 %.2f）",
                task_id, sug.template_task_id, sug.confidence,
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("[复用] 写复用建议失败（可忽略）: %s", e)


async def render_reuse_into_task(
    decision: dict, task_dir: Path, question_text: str, title: str, user_id: str,
) -> Optional[dict]:
    """自动复用路径：渲染复用产物并落库，返回新 teaching_data（供 pipeline 早退）。"""
    return await render_reuse(decision, task_dir.name, question_text, title, user_id)
