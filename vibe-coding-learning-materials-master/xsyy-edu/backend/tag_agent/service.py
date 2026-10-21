# -*- coding: utf-8 -*-
"""标签识别智能体业务服务.

职责（阶段二起，预加入 → 预修改）：
- 预修改审核队列：创建 / 列表 / 审核（按 operation 应用：增/改/删/合并）+ 批量审核
- 题目标签审核队列：题目级标签建议的创建 / 列表 / 审核（确认后才写题目）
- 审核后同步题目引用（方案"七.4"）
- 学习闭环记录（方案"九"）
- 识别日志（准确率监控）
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tag_agent.models import (
    PendingTag,
    PendingTagOperation,
    PendingTagStatus,
    QuestionTagProposal,
    QuestionTagProposalStatus,
    RecognitionLog,
    TagLearningRecord,
)
from tag_agent.orchestrator import (
    RecognitionOutcome,
    build_knowledge_tags,
)
from tag_agent.tag_library import TagLibrary

logger = logging.getLogger(__name__)


# ── 正式标签库写入（审核通过后）─────────────────────────────────────────────


def promote_to_official(
    library: TagLibrary,
    *,
    domain: str,
    grade: str,
    chapter: str,
    tag: str,
    keywords: list[str] | None = None,
) -> None:
    """审核通过后把标签写入正式标签库.

    当前写入内存索引与关键词库；配置 remote_db_url 后应同步写入
    knowledge_tag_framework 表（预留，见 tag_library._load_from_remote_db）。
    """
    hierarchy = library.hierarchy
    chapter_tags = hierarchy.setdefault(domain, {}).setdefault(grade, {}).setdefault(chapter, [])
    if tag and tag not in chapter_tags:
        chapter_tags.append(tag)
    if tag:
        library.tag_info[tag] = {"domain": domain, "grade": grade, "chapter": chapter}
    if keywords:
        library.add_keywords(tag, keywords)
    logger.info(
        "正式标签库新增: 知识域=%s 年级=%s 章/单元=%s 知识点标签=%s 关键词=%s",
        domain, grade, chapter, tag, keywords,
    )


# ── 预加入库 ─────────────────────────────────────────────────────────────────


async def create_pending(db: AsyncSession, payload: dict, temp_question_ids: list[str]) -> PendingTag:
    """创建预修改审核队列记录（智能体产出的增/改/删/合并提案）. """
    record = PendingTag(
        operation=payload.get("operation", PendingTagOperation.ADD),
        domain=payload.get("domain", ""),
        grade=payload.get("grade", ""),
        chapter=payload.get("chapter", ""),
        tag_name=payload.get("tag_name", ""),
        keywords=payload.get("keywords") or [],
        target_domain=payload.get("target_domain", ""),
        target_grade=payload.get("target_grade", ""),
        target_chapter=payload.get("target_chapter", ""),
        target_tag=payload.get("target_tag", ""),
        before_snapshot=payload.get("before") or payload.get("before_snapshot"),
        after_snapshot=payload.get("after") or payload.get("after_snapshot"),
        evidence=payload.get("evidence", ""),
        source_question_id=payload.get("source_question_id", ""),
        source_question_text=payload.get("source_question_text", ""),
        created_by=payload.get("created_by", ""),
        status=PendingTagStatus.PENDING,
        agent_reason=payload.get("agent_reason", ""),
        confidence=float(payload.get("confidence", 0.0)),
        temp_question_ids=temp_question_ids,
        is_chapter_level=bool(payload.get("is_chapter_level", False)),
        candidate_chapters=payload.get("candidate_chapters") or [],
        no_match_reason=payload.get("no_match_reason", ""),
    )
    db.add(record)
    await db.flush()
    return record


async def list_pending(
    db: AsyncSession,
    *,
    status: str = "",
    operation: str = "",
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[PendingTag]]:
    """分页列出预修改提案，可过滤状态与操作类型."""
    query = select(PendingTag)
    count_query = select(func.count()).select_from(PendingTag)
    if status:
        query = query.where(PendingTag.status == status)
        count_query = count_query.where(PendingTag.status == status)
    if operation:
        query = query.where(PendingTag.operation == operation)
        count_query = count_query.where(PendingTag.operation == operation)
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(PendingTag.created_at.desc()).offset((page - 1) * size).limit(size)
    )
    return total, list(result.scalars().all())


async def get_pending(db: AsyncSession, pending_id: str) -> PendingTag | None:
    return await db.get(PendingTag, pending_id)


async def list_pending_names(
    db: AsyncSession,
    domain: str,
    grade: str,
    chapter: str,
) -> list[str]:
    """返回同域同章下的预加入知识点标签名（供智能体生成前查重）."""
    result = await db.execute(
        select(PendingTag.tag_name).where(
            PendingTag.domain == domain,
            PendingTag.grade == grade,
            PendingTag.chapter == chapter,
            PendingTag.status.in_([PendingTagStatus.PENDING]),
        )
    )
    return list(result.scalars().all())


# ── 去重提案落库（阶段三：DedupAgent 提案 → 合并提案进审核队列）────────────


async def persist_duplicate_proposals(
    db: AsyncSession,
    proposals: list,
    *,
    created_by: str = "dedup_agent",
) -> list[PendingTag]:
    """把去重扫描提案写入预修改审核队列（operation=merge）.

    查重策略：同 duplicate_tag + 状态 pending 的 merge 提案已存在则跳过，
    避免重复落库；duplicate_tag 为空/不在正式库的提案跳过。
    """
    records: list[PendingTag] = []
    for p in proposals:
        dup_tag = getattr(p, "duplicate_tag", "") or ""
        if not dup_tag:
            continue
        # 去重：已存在同目标待审合并提案则跳过
        exists = await db.execute(
            select(PendingTag).where(
                PendingTag.operation == PendingTagOperation.MERGE,
                PendingTag.status == PendingTagStatus.PENDING,
                PendingTag.target_tag == dup_tag,
            )
        )
        if exists.scalars().first() is not None:
            continue

        # 定位重复标签归属（raw.info 由 DedupAgent 带入）
        raw = getattr(p, "raw", None) or {}
        info = (raw.get("info") or {}) if isinstance(raw, dict) else {}
        record = PendingTag(
            operation=PendingTagOperation.MERGE,
            domain=info.get("domain", ""),
            grade=info.get("grade", ""),
            chapter=info.get("chapter", ""),
            tag_name=dup_tag,
            target_domain=info.get("domain", ""),
            target_grade=info.get("grade", ""),
            target_chapter=info.get("chapter", ""),
            target_tag=dup_tag,
            after_snapshot={"primary_tag": getattr(p, "primary_tag", "") or ""},
            evidence=getattr(p, "evidence", "") or "",
            confidence=float(getattr(p, "confidence", 0.0) or 0.0),
            agent_reason=f"去重检测：与「{getattr(p, 'primary_tag', '')}」相似度 "
                         f"{float(getattr(p, 'similarity', 0) or 0):.2f}，建议合并",
            created_by=created_by,
            status=PendingTagStatus.PENDING,
        )
        db.add(record)
        records.append(record)
    await db.flush()
    return records


# ── 审核（方案"七"，阶段二：按 operation 应用增/改/删/合并）─────────────────


async def review_pending(
    db: AsyncSession,
    library: TagLibrary,
    *,
    pending_id: str,
    action: str,
    admin_id: str,
    admin_note: str = "",
    reject_reason: str = "",
    modified: Optional[dict] = None,
    merged_to_tag: str = "",
    confirmed: bool = False,
    sync_framework: bool = True,
) -> dict:
    """审核预修改审核队列中的一条提案（按 operation 应用）.

    action: approve / approve_modified / merge / reject
    提案的 operation（add/modify/delete/merge）决定应用逻辑：
      - add    → 写入正式库（promote_to_official）
      - modify → 按 after_snapshot（可被 modified 覆盖）更新已有标签
      - delete → 硬删除正式库记录（需 confirmed=True 二次确认）
      - merge  → 合并重复标签（primary 来自 merged_to_tag 或 after_snapshot）

    支持"审核后修改审核"：已处理记录可重新审核（覆盖状态并重放副作用），
    状态变更写入 review_history，驳回必须填写 reject_reason。
    审核生效后（sync_framework=True，默认）自动把内存正式库差量写回
    knowledge_tag_framework 表（识别哪个库就写哪个库，见 framework_sync）。

    Returns:
        审核结果，含 reference_updates（题目引用同步映射，供宿主应用写入）。
    """
    pending = await get_pending(db, pending_id)
    if pending is None:
        raise ValueError(f"预修改提案不存在: {pending_id}")
    # 支持"审核后修改审核"：允许对已处理记录重新审核（仅覆盖状态/副作用，不重复建表）
    prev_status = pending.status

    action = (action or "").strip()
    valid = ("approve", "approve_modified", "merge", "reject")
    if action not in valid:
        raise ValueError(f"无效的审核动作: {action}")
    if action == "reject" and not (reject_reason or "").strip():
        raise ValueError("驳回必须填写驳回原因，便于智能体学习为什么被驳回")

    operation = pending.operation or PendingTagOperation.ADD

    # 提取当前（或修改后）的标签属性
    domain = (modified or {}).get("domain") or pending.domain
    grade = (modified or {}).get("grade") or pending.grade
    chapter = (modified or {}).get("chapter") or pending.chapter
    tag = (modified or {}).get("tag_name") or pending.tag_name
    keywords = (modified or {}).get("keywords") or pending.keywords or []

    # 被操作标签定位（modify/delete/merge 使用）
    target_domain = pending.target_domain or pending.domain
    target_grade = pending.target_grade or pending.grade
    target_chapter = pending.target_chapter or pending.chapter
    target_tag = pending.target_tag or pending.tag_name

    reference_updates: dict[str, dict] = {}
    pending_changed: Optional[dict] = None
    pending.reviewed_by = admin_id
    pending.reviewed_at = datetime.utcnow()
    pending.admin_note = admin_note
    pending.reject_reason = (reject_reason or "").strip() if action == "reject" else ""

    if action in ("approve", "approve_modified"):
        # 删除操作必须先二次确认（放在状态变更之前，防止失败调用污染状态）
        if operation == PendingTagOperation.DELETE and not confirmed:
            raise ValueError("删除操作必须二次确认（confirmed=true），且由管理员执行")
        pending.status = (
            PendingTagStatus.APPROVED_MODIFIED if action == "approve_modified"
            else PendingTagStatus.APPROVED
        )

        if operation == PendingTagOperation.DELETE:
            # ── 删除：硬删除正式库记录（用户确认：删除数据库记录）──────────
            library.delete_tag(
                domain=target_domain, grade=target_grade,
                chapter=target_chapter, tag=target_tag,
            )
            pending.merged_to_tag = ""
            reference_updates = {
                qid: build_knowledge_tags(
                    "", "", "", "",
                    tag_source="official", pending_review_status="deleted",
                    created_by_agent=False,
                )
                for qid in pending.temp_question_ids or []
            }
            for kt in reference_updates.values():
                kt["needs_retag"] = True  # 标签被删除，题目需重新识别
            pending_changed = {
                "before": pending.before_snapshot or {
                    "domain": target_domain, "grade": target_grade,
                    "chapter": target_chapter, "tag": target_tag,
                },
                "after": None,
                "deleted_at": datetime.utcnow().isoformat(),
            }

        elif operation == PendingTagOperation.MERGE:
            # ── 合并：duplicate 并入 primary ────────────────────────────────
            primary = merged_to_tag or (
                (pending.after_snapshot or {}).get("primary_tag")
                or (pending.after_snapshot or {}).get("merged_to_tag")
                or ""
            )
            if not primary:
                raise ValueError("merge 提案必须提供 merged_to_tag（保留方）")
            if library.find_tag(primary) is None:
                raise ValueError(f"目标正式标签不存在: {primary}")
            library.merge_tags(primary, target_tag)
            pending.merged_to_tag = primary
            target = library.find_tag(primary)
            reference_updates = build_reference_updates(
                pending, tag_source="official", review_status="merged",
                final_domain=target["domain"], final_grade=target["grade"],
                final_chapter=target["chapter"], final_tag=primary,
            )

        elif operation == PendingTagOperation.MODIFY:
            # ── 修改：按 after 快照（可被管理员 modified 覆盖）更新已有标签 ──
            after = dict(pending.after_snapshot or {})
            if modified:
                for k, v in modified.items():
                    if v:
                        after[k] = v
            library.update_tag(
                domain=target_domain, grade=target_grade,
                chapter=target_chapter, tag=target_tag,
                after=after,
            )
            final_tag = (after.get("tag_name") or target_tag)
            reference_updates = build_reference_updates(
                pending, tag_source="official", review_status="approved",
                final_domain=after.get("domain") or target_domain,
                final_grade=after.get("grade") or target_grade,
                final_chapter=after.get("chapter") or target_chapter,
                final_tag=final_tag,
            )
            pending_changed = {
                "before": pending.before_snapshot,
                "after": after,
            }

        else:
            # ── 新增（add，兼容原预加入语义）──────────────────────────────
            promote_to_official(
                library, domain=domain, grade=grade,
                chapter=chapter, tag=tag, keywords=keywords,
            )
            reference_updates = build_reference_updates(
                pending, tag_source="official", review_status="approved",
                final_domain=domain, final_grade=grade,
                final_chapter=chapter, final_tag=tag,
            )

    elif action == "merge":
        # 合并到已有标签：不新增，把题目引用改为目标正式标签
        if not merged_to_tag:
            raise ValueError("merge 操作必须提供 merged_to_tag")
        target = library.find_tag(merged_to_tag)
        if not target:
            raise ValueError(f"目标正式标签不存在: {merged_to_tag}")
        pending.status = PendingTagStatus.MERGED
        pending.merged_to_tag = merged_to_tag
        reference_updates = build_reference_updates(
            pending, tag_source="official", review_status="merged",
            final_domain=target["domain"], final_grade=target["grade"],
            final_chapter=target["chapter"], final_tag=merged_to_tag,
        )

    elif action == "reject":
        # 驳回：不生效，保留历史记录，提示题目重新识别
        pending.status = PendingTagStatus.REJECTED
        reference_updates = build_reference_updates(
            pending, tag_source="pre_joined", review_status="rejected",
            final_domain=domain, final_grade=grade,
            final_chapter=chapter, final_tag=tag,
            needs_retag=True,
        )

    # ── 审核后修改审核：记录状态变更轨迹（from→to / 操作 / 原因）──
    history_entry = {
        "from": prev_status,
        "to": pending.status,
        "action": action,
        "by": admin_id,
        "reason": pending.reject_reason,
        "at": datetime.utcnow().isoformat(),
    }
    pending.review_history = (pending.review_history or []) + [history_entry]
    # 由"已通过/已修改通过/已合并"改回"驳回"时，对内存库做幂等回退（仅 add 可安全反写）
    if (
        action == "reject"
        and prev_status in (
            PendingTagStatus.APPROVED,
            PendingTagStatus.APPROVED_MODIFIED,
            PendingTagStatus.MERGED,
        )
        and operation == PendingTagOperation.ADD
    ):
        try:
            library.delete_tag(domain=domain, grade=grade, chapter=chapter, tag=tag)
        except Exception:  # noqa: BLE001
            logger.warning("重新审核驳回时回退内存库标签失败（进程重启后自动一致）: %s", pending.id)

    # 学习闭环记录（方案"九"）
    db.add(TagLearningRecord(
        action_type=f"review_{action}",
        question_id=pending.source_question_id,
        domain=pending.domain,
        grade=pending.grade,
        chapter=pending.chapter,
        tag_name=pending.tag_name,
        agent_data={
            "operation": operation,
            "reason": pending.agent_reason,
            "confidence": pending.confidence,
            "keywords": pending.keywords or [],
            "target": {
                "domain": target_domain, "grade": target_grade,
                "chapter": target_chapter, "tag": target_tag,
            },
        },
        admin_data={
            "action": action,
            "note": admin_note,
            "modified": modified or {},
            "merged_to_tag": merged_to_tag,
            "changed": pending_changed,
        },
        note=f"管理员 {admin_id} 审核「{action}」operation={operation}",
    ))
    await db.commit()
    await db.refresh(pending)

    # ── 审核生效后：把内存正式库差量写回 knowledge_tag_framework 表 ──
    # "识别到哪个库就使用哪个库"：TagLibrary 从哪个库加载就写回哪个库
    # （framework_sync 复用 tag_agent.db.get_engine()，与加载源同库）。
    if sync_framework:
        try:
            from tag_agent.framework_sync import clear_framework_caches, sync_library_to_framework
            if await sync_library_to_framework(library):
                clear_framework_caches()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "正式标签库回写失败（内存库已生效，进程重启后从表重新加载时以表为准）: %s",
                e,
            )

    return {
        "pending_id": pending.id,
        "operation": operation,
        "status": pending.status,
        "reference_updates": reference_updates,
    }


# ── 批量审核（阶段二：管理员可勾选多条一次通过/驳回/合并）──────────────────


async def batch_review_pending(
    db: AsyncSession,
    library: TagLibrary,
    *,
    pending_ids: list[str],
    action: str,
    admin_id: str,
    admin_note: str = "",
    merged_to_tag: str = "",
    confirmed: bool = False,
) -> dict:
    """批量审核多条预修改提案（逐条应用，单条失败不影响其余）."""
    results: dict[str, dict] = {}
    ok_count = fail_count = 0
    for pid in pending_ids:
        try:
            r = await review_pending(
                db, library,
                pending_id=pid, action=action, admin_id=admin_id,
                admin_note=admin_note, merged_to_tag=merged_to_tag,
                confirmed=confirmed,
                sync_framework=False,  # 批量结束后统一回写一次
            )
            results[pid] = {"ok": True, **r}
            ok_count += 1
        except Exception as e:  # noqa: BLE001
            results[pid] = {"ok": False, "error": str(e)}
            fail_count += 1
    await db.commit()

    # 批量审核生效后：统一把内存正式库差量写回 knowledge_tag_framework 表
    try:
        from tag_agent.framework_sync import clear_framework_caches, sync_library_to_framework
        if await sync_library_to_framework(library):
            clear_framework_caches()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "正式标签库批量回写失败（内存库已生效，进程重启后从表重新加载时以表为准）: %s",
            e,
        )

    return {
        "total": len(pending_ids),
        "ok_count": ok_count,
        "fail_count": fail_count,
        "results": results,
    }


# ── 题目标签审核队列（阶段二：题目级标签全人工审核）────────────────────────


async def create_question_proposal(
    db: AsyncSession,
    *,
    question_id: str,
    question_text: str,
    outcome: RecognitionOutcome,
) -> QuestionTagProposal:
    """把一次识别结果写入题目标签审核队列（待管理员确认后才写题目）.

    同题去重：该题已有「待审核」提案时直接返回既有记录，不重复入队
    （生成主链路 persist 后，详情页 ensure-complete 的标签补全可能对
    同一题再次调用 persist_recognition）。
    """
    if question_id:
        existing = (await db.execute(
            select(QuestionTagProposal)
            .where(
                QuestionTagProposal.question_id == question_id,
                QuestionTagProposal.status == QuestionTagProposalStatus.PENDING,
            )
            .order_by(QuestionTagProposal.created_at.desc())
            .limit(1)
        )).scalars().first()
        if existing is not None:
            return existing
    record = QuestionTagProposal(
        question_id=question_id,
        question_text=question_text[:1000],
        domain=outcome.domain,
        grade=outcome.grade,
        chapter=outcome.chapter,
        sub_tags=[outcome.tag] if outcome.tag else [],
        confidence=outcome.confidence,
        source_action=outcome.action,
        status=QuestionTagProposalStatus.PENDING,
        agent_data={
            "reasoning": outcome.reasoning,
            "matched_existing": outcome.matched_existing,
            "action": outcome.action,
        },
    )
    db.add(record)
    await db.flush()
    return record


async def list_question_proposals(
    db: AsyncSession,
    *,
    status: str = "",
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[QuestionTagProposal]]:
    """分页列出题目标签审核队列，可过滤状态."""
    query = select(QuestionTagProposal)
    count_query = select(func.count()).select_from(QuestionTagProposal)
    if status:
        query = query.where(QuestionTagProposal.status == status)
        count_query = count_query.where(QuestionTagProposal.status == status)
    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(
        query.order_by(QuestionTagProposal.created_at.desc())
        .offset((page - 1) * size).limit(size)
    )
    return total, list(result.scalars().all())


async def get_question_proposal(db: AsyncSession, proposal_id: str) -> QuestionTagProposal | None:
    return await db.get(QuestionTagProposal, proposal_id)


async def review_question_proposal(
    db: AsyncSession,
    *,
    proposal_id: str,
    action: str,
    admin_id: str,
    admin_note: str = "",
    reject_reason: str = "",
    modified: Optional[dict] = None,
) -> dict:
    """审核题目标签建议（approve / approve_modified / reject）.

    支持"审核后修改审核"：已处理记录可重新审核（覆盖状态并重放题目标签写入），
    状态变更写入 review_history，驳回必须填写 reject_reason。

    Returns:
        {"status", "applied", "prev_applied", "knowledge_tags"} — 宿主应用据此写题目
        knowledge_tags（teachings 表 + metadata）。
    """
    prop = await get_question_proposal(db, proposal_id)
    if prop is None:
        raise ValueError(f"题目标签建议不存在: {proposal_id}")
    # 支持"审核后修改审核"：允许对已处理记录重新审核
    prev_status = prop.status
    prev_applied = bool(prop.applied)

    action = (action or "").strip()
    if action not in ("approve", "approve_modified", "reject"):
        raise ValueError(f"无效的审核动作: {action}")
    if action == "reject" and not (reject_reason or "").strip():
        raise ValueError("驳回必须填写驳回原因，便于智能体学习为什么被驳回")

    domain = (modified or {}).get("domain") or prop.domain
    grade = (modified or {}).get("grade") or prop.grade
    chapter = (modified or {}).get("chapter") or prop.chapter
    sub_tags = (modified or {}).get("sub_tags") or prop.sub_tags or []

    prop.reviewed_by = admin_id
    prop.reviewed_at = datetime.utcnow()
    prop.admin_note = admin_note
    prop.reject_reason = (reject_reason or "").strip() if action == "reject" else ""

    knowledge_tags: Optional[dict] = None
    if action == "reject":
        prop.status = QuestionTagProposalStatus.REJECTED
        prop.applied = False
    else:
        prop.status = (
            QuestionTagProposalStatus.APPROVED_MODIFIED
            if action == "approve_modified"
            else QuestionTagProposalStatus.APPROVED
        )
        prop.applied = True
        knowledge_tags = {
            "domain": domain,
            "grade": grade,
            "main_tag": chapter,
            "sub_tags": sub_tags,
            "tag_source": "official",
            "pending_review_status": prop.status,
            "created_by_agent": True,
        }

    # ── 审核后修改审核：记录状态变更轨迹 ──
    history_entry = {
        "from": prev_status,
        "to": prop.status,
        "action": action,
        "by": admin_id,
        "reason": prop.reject_reason,
        "at": datetime.utcnow().isoformat(),
    }
    prop.review_history = (prop.review_history or []) + [history_entry]

    db.add(TagLearningRecord(
        action_type=f"question_review_{action}",
        question_id=prop.question_id,
        domain=prop.domain,
        grade=prop.grade,
        chapter=prop.chapter,
        tag_name="、".join(prop.sub_tags or []),
        agent_data={
            "confidence": prop.confidence,
            "source_action": prop.source_action,
            "reasoning": (prop.agent_data or {}).get("reasoning", ""),
        },
        admin_data={"action": action, "note": admin_note, "modified": modified or {}},
        note=f"管理员 {admin_id} 审核题目标签「{action}」",
    ))
    await db.commit()
    await db.refresh(prop)

    return {
        "proposal_id": prop.id,
        "question_id": prop.question_id,
        "status": prop.status,
        "applied": prop.applied,
        "prev_applied": prev_applied,
        "knowledge_tags": knowledge_tags,
    }


def build_reference_updates(
    pending: PendingTag,
    *,
    tag_source: str,
    review_status: str,
    final_domain: str,
    final_grade: str,
    final_chapter: str,
    final_tag: str,
    needs_retag: bool = False,
) -> dict[str, dict]:
    """生成临时使用题目的引用同步映射（方案"七.4"）.

    宿主应用按 {question_id: knowledge_tags} 更新题目标签。
    """
    updates: dict[str, dict] = {}
    for qid in pending.temp_question_ids or []:
        kt = build_knowledge_tags(
            final_domain, final_grade, final_chapter, final_tag,
            tag_source=tag_source,
            pending_tag_id=pending.id,
            temporary_use=False,
            pending_review_status=review_status,
            created_by_agent=True,
        )
        if needs_retag:
            kt["needs_retag"] = True  # 提示题目重新识别或人工选择
        updates[qid] = kt
    return updates


# ── 学习闭环记录 ─────────────────────────────────────────────────────────────


async def record_learning(
    db: AsyncSession,
    *,
    action_type: str,
    question_id: str = "",
    domain: str = "",
    grade: str = "",
    chapter: str = "",
    tag_name: str = "",
    agent_data: Optional[dict] = None,
    admin_data: Optional[dict] = None,
    note: str = "",
) -> TagLearningRecord:
    record = TagLearningRecord(
        action_type=action_type,
        question_id=question_id,
        domain=domain,
        grade=grade,
        chapter=chapter,
        tag_name=tag_name,
        agent_data=agent_data,
        admin_data=admin_data,
        note=note,
    )
    db.add(record)
    await db.flush()
    return record


async def list_learning_records(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[TagLearningRecord]]:
    total = (await db.execute(select(func.count()).select_from(TagLearningRecord))).scalar() or 0
    result = await db.execute(
        select(TagLearningRecord).order_by(TagLearningRecord.created_at.desc())
        .offset((page - 1) * size).limit(size)
    )
    return total, list(result.scalars().all())


async def delete_learning_records(
    db: AsyncSession,
    *,
    ids: list[str],
) -> int:
    """按 id 列表硬删除学习闭环记录，返回实际删除条数。"""
    if not ids:
        return 0
    res = await db.execute(
        delete(TagLearningRecord).where(TagLearningRecord.id.in_(ids))
    )
    await db.commit()
    return res.rowcount or 0


# ── 识别日志 ─────────────────────────────────────────────────────────────────


async def log_recognition(
    db: AsyncSession,
    *,
    question: str,
    outcome: RecognitionOutcome,
    pending_tag_id: str = "",
) -> RecognitionLog:
    log = RecognitionLog(
        question=question,
        is_math_problem=outcome.is_math_problem,
        domain=outcome.domain,
        grade=outcome.grade,
        chapter=outcome.chapter,
        tag_name=outcome.tag,
        confidence=outcome.confidence,
        action=outcome.action,
        matched_existing=outcome.matched_existing,
        pending_tag_id=pending_tag_id,
        raw_result=outcome.raw,
    )
    db.add(log)
    await db.flush()
    return log


async def list_recognition_logs(
    db: AsyncSession,
    *,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[RecognitionLog]]:
    total = (await db.execute(select(func.count()).select_from(RecognitionLog))).scalar() or 0
    result = await db.execute(
        select(RecognitionLog).order_by(RecognitionLog.created_at.desc())
        .offset((page - 1) * size).limit(size)
    )
    return total, list(result.scalars().all())


# ── 一站式持久化（识别结果落地）─────────────────────────────────────────────


async def persist_recognition(
    db: AsyncSession,
    *,
    question: str,
    outcome: RecognitionOutcome,
    question_id: str = "",
    creator_id: str = "",
) -> dict:
    """把一次识别结果持久化：库级提案入库（增/改/删）+ 题目标签入审核队列 + 日志.

    Returns:
        {**outcome.to_dict(), "pending_tag_id": ..., "question_proposal_id": ...,
         "reference_updates": {...}}
    """
    result = outcome.to_dict()
    pending_id = ""
    question_proposal_id = ""

    # ── 库级提案（阶段二：增/改/删/合并全部先入预修改审核队列）──────────
    if outcome.action in ("create_pending_tag", "create_pending_chain") and outcome.pending_payload:
        # 新增提案（场景二/三）
        pending = await create_pending(
            db, {**outcome.pending_payload, "operation": "add"},
            temp_question_ids=[question_id] if question_id else [],
        )
        pending_id = pending.id
        result["pending_tag_id"] = pending_id
        result["reference_updates"] = {
            question_id: build_knowledge_tags(
                outcome.domain, outcome.grade, outcome.chapter, outcome.tag,
                tag_source="pre_joined",
                pending_tag_id=pending_id,
                temporary_use=True,
                pending_review_status="pending",
                created_by_agent=True,
            )
        } if question_id else {}
        await record_learning(
            db,
            action_type="create_pending",
            question_id=question_id,
            domain=outcome.domain,
            grade=outcome.grade,
            chapter=outcome.chapter,
            tag_name=outcome.tag,
            agent_data={
                "operation": "add",
                "reason": outcome.reasoning,
                "confidence": outcome.confidence,
                "keywords": (outcome.pending_payload or {}).get("keywords", []),
                "is_chapter_level": (outcome.pending_payload or {}).get("is_chapter_level", False),
            },
            note="智能体创建新增标签提案（预修改）",
        )
    elif outcome.action == "propose_modify" and outcome.proposal_payload:
        # 修改提案（阶段一改造：补关键词等不再直写，先进审核队列）
        pending = await create_pending(
            db, {**outcome.proposal_payload, "operation": "modify"},
            temp_question_ids=[question_id] if question_id else [],
        )
        pending_id = pending.id
        result["pending_tag_id"] = pending_id
        result["reference_updates"] = {}
        await record_learning(
            db,
            action_type="propose_modify",
            question_id=question_id,
            domain=outcome.domain,
            grade=outcome.grade,
            chapter=outcome.chapter,
            tag_name=outcome.tag,
            agent_data={
                "operation": "modify",
                "payload": outcome.proposal_payload,
                "keywords": outcome.keyword_added,
            },
            note="智能体产出修改提案（补关键词，待管理员审核）",
        )
    elif outcome.action == "add_keywords" and outcome.keyword_added:
        # 兼容旧行为（如直连调用场景），记录学习样本
        await record_learning(
            db,
            action_type="extract_keyword",
            question_id=question_id,
            domain=outcome.domain,
            grade=outcome.grade,
            chapter=outcome.chapter,
            tag_name=outcome.tag,
            agent_data={"keywords": outcome.keyword_added},
            note="智能体补充强特征关键词（兼容记录）",
        )

    # ── 题目标签审核队列（阶段二决策：题目级标签全部人工审核）──────────
    if question_id and outcome.action in (
        "inject_official", "propose_modify",
        "create_pending_tag", "create_pending_chain",
    ) and outcome.domain and outcome.tag:
        qp = await create_question_proposal(
            db, question_id=question_id, question_text=question, outcome=outcome,
        )
        question_proposal_id = qp.id
        result["question_proposal_id"] = question_proposal_id

    await log_recognition(db, question=question, outcome=outcome, pending_tag_id=pending_id)
    await db.commit()
    return result


# ── 监控统计（阶段五：识别质量 + 审核闭环数据飞轮）────────────────────────


async def get_stats(db: AsyncSession) -> dict:
    """聚合统计：识别日志 / 审核队列 / 题目队列 / 学习记录（供监控面板）."""
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    day_ago = now - timedelta(days=1)

    # ── 识别日志 ──
    log_total = (await db.execute(select(func.count()).select_from(RecognitionLog))).scalar() or 0
    log_today = (await db.execute(
        select(func.count()).select_from(RecognitionLog).where(RecognitionLog.created_at >= day_ago)
    )).scalar() or 0
    log_avg_conf = (await db.execute(
        select(func.avg(RecognitionLog.confidence)).select_from(RecognitionLog)
    )).scalar()
    # action（source）分布
    action_rows = (await db.execute(
        select(RecognitionLog.action, func.count()).group_by(RecognitionLog.action)
    )).all()
    action_dist = {a: c for a, c in action_rows}
    failed_count = int(action_dist.get("failed", 0)) + int(action_dist.get("low_confidence", 0))

    # ── 预修改审核队列（pending） ──
    pending_rows = (await db.execute(
        select(PendingTag.status, func.count()).group_by(PendingTag.status)
    )).all()
    pending_status = {s: c for s, c in pending_rows}
    op_rows = (await db.execute(
        select(PendingTag.operation, func.count()).group_by(PendingTag.operation)
    )).all()
    pending_ops = {o: c for o, c in op_rows}
    pending_total = int(pending_status.get("pending", 0))
    handled = (
        int(pending_status.get("approved", 0))
        + int(pending_status.get("approved_modified", 0))
        + int(pending_status.get("merged", 0))
        + int(pending_status.get("rejected", 0))
    )

    # ── 题目标签审核队列 ──
    qp_rows = (await db.execute(
        select(QuestionTagProposal.status, func.count()).group_by(QuestionTagProposal.status)
    )).all()
    qp_status = {s: c for s, c in qp_rows}
    qp_pending = int(qp_status.get("pending", 0))
    qp_handled = (
        int(qp_status.get("approved", 0))
        + int(qp_status.get("approved_modified", 0))
        + int(qp_status.get("rejected", 0))
    )

    # ── 学习记录（近 7 天） ──
    learn_7d = (await db.execute(
        select(func.count()).select_from(TagLearningRecord)
        .where(TagLearningRecord.created_at >= now - timedelta(days=7))
    )).scalar() or 0

    return {
        "recognition": {
            "total": log_total,
            "today": log_today,
            "avg_confidence": round(float(log_avg_conf), 4) if log_avg_conf is not None else None,
            "by_action": action_dist,
            "failed_count": failed_count,
        },
        "pending_queue": {
            "by_status": pending_status,
            "by_operation": pending_ops,
            "pending": pending_total,
            "handled": handled,
            "approve_rate": round(handled / (pending_total + handled), 4) if (pending_total + handled) else None,
            "backlog_warning": pending_total > 200,
        },
        "question_queue": {
            "by_status": qp_status,
            "pending": qp_pending,
            "handled": qp_handled,
        },
        "learning_7d": learn_7d,
        "generated_at": now.isoformat(),
    }

# ============================================================================
# P1.5 补丁：追加到 backend/tag_agent/service.py 末尾
# 作用：标签增强建议的列表查询 + 审核应用（通过即并入词库并回写）。
# 合并方式：整段复制到 service.py 末尾即可。
# 说明：函数内使用懒导入，避免与文件顶部 import 块冲突；logger 局部定义保证可用。
# ============================================================================

async def list_label_suggestions(
    db, *, status: str | None = None, page: int = 1, size: int = 20,
) -> tuple[int, list]:
    """标签增强建议审核队列列表（按创建时间倒序）.

    Returns:
        (total, items) — items 为 LabelSuggestion ORM 对象列表
    """
    import logging
    from sqlalchemy import func, select

    from tag_agent.models import LabelSuggestion

    logger = logging.getLogger(__name__)
    count_stmt = select(func.count()).select_from(LabelSuggestion)
    if status:
        count_stmt = count_stmt.where(LabelSuggestion.status == status)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = select(LabelSuggestion).order_by(LabelSuggestion.created_at.desc())
    if status:
        stmt = stmt.where(LabelSuggestion.status == status)
    offset = max(0, (page - 1) * size)
    rows = (await db.execute(stmt.offset(offset).limit(size))).scalars().all()
    return total, list(rows)


async def review_label_suggestion(
    db,
    library,
    *,
    suggestion_id: str,
    action: str,
    admin_id: str,
    approved_keywords: list[str] | None = None,
    admin_note: str = "",
    reject_reason: str = "",
) -> dict:
    """审核单条标签增强建议.

    action=approve：将管理员勾选（或默认非“疑似过窄”）的判词并入标签 B 的关键词集合，
        再 sync_library_to_framework + clear_framework_caches 回写正式库。
    action=reject：仅记录，不入库；必须填写 reject_reason（供智能体学习“为什么被驳回”）。

    全程留痕（TagLearningRecord + review_history）。
    """
    import logging
    from datetime import datetime
    from sqlalchemy import select

    from tag_agent.framework_sync import clear_framework_caches, sync_library_to_framework
    from tag_agent.models import LabelSuggestion, LabelSuggestionStatus, TagLearningRecord

    logger = logging.getLogger(__name__)
    sug = (
        await db.execute(select(LabelSuggestion).where(LabelSuggestion.id == suggestion_id))
    ).scalar_one_or_none()
    if sug is None:
        raise ValueError(f"标签增强建议不存在: {suggestion_id}")

    action = (action or "").strip()
    if action not in ("approve", "reject"):
        raise ValueError(f"无效的审核动作: {action}")
    prev_status = sug.status

    applied: list[str] = []
    if action == "reject":
        if not (reject_reason or "").strip():
            raise ValueError("驳回必须填写驳回原因，便于智能体学习为什么被驳回")
        sug.status = LabelSuggestionStatus.REJECTED
        sug.reject_reason = (reject_reason or "").strip()
    else:
        cands = sug.candidates or []
        if approved_keywords is not None:
            applied = [k for k in approved_keywords if k]
        else:
            # 默认：采纳所有“非疑似过窄”的候选判词
            applied = [
                c["keyword"] for c in cands
                if isinstance(c, dict) and not c.get("too_narrow") and c.get("keyword")
            ]
        if not applied:
            raise ValueError("没有可并入的判词（候选全部疑似过窄或为空），请至少勾选 1 条或全部驳回")
        # 并入词库（仅增强“判词命中”一环）
        library.add_keywords(sug.new_tag, applied)
        sug.status = LabelSuggestionStatus.APPROVED

    sug.reviewed_by = admin_id
    sug.reviewed_at = datetime.utcnow()
    sug.admin_note = admin_note
    sug.review_history = (sug.review_history or []) + [{
        "from": prev_status,
        "to": sug.status,
        "action": action,
        "by": admin_id,
        "at": datetime.utcnow().isoformat(),
        "applied_keywords": applied,
    }]
    db.add(TagLearningRecord(
        action_type="label_learning_approve" if action == "approve" else "label_learning_reject",
        question_id=sug.task_id,
        domain=sug.new_tag_domain,
        grade=sug.new_tag_grade,
        chapter=sug.new_tag_chapter,
        tag_name=sug.new_tag,
        agent_data={"candidates": sug.candidates},
        admin_data={
            "action": action,
            "applied_keywords": applied,
            "note": admin_note,
        },
        note=f"管理员 {admin_id} {action} 标签增强建议（标签 {sug.new_tag}）",
    ))
    await db.commit()
    await db.refresh(sug)

    # 审核生效后：把内存正式库差量写回 knowledge_tag_framework 表 + 清宿主缓存
    if action == "approve":
        try:
            if await sync_library_to_framework(library):
                clear_framework_caches()
        except Exception as e:  # noqa: BLE001
            logger.warning("标签增强建议回写失败（内存库已生效，重启后从表重新加载）: %s", e)

    return {
        "suggestion_id": sug.id,
        "status": sug.status,
        "applied_keywords": applied,
    }
# ============================================================================
# P3 补丁：追加到 backend/tag_agent/service.py 末尾
# 作用：复用建议审核队列 / 题型提示词沉淀审核队列 的列表 + 审核逻辑。
# 合并方式：整段复制到 service.py 末尾即可（函数体内，与现有 review_label_suggestion 同级）。
# 依赖：schemas.py 需补 ReuseSuggestionQuery / ReuseSuggestionReviewRequest / PatternSuggestionQuery / PatternSuggestionReviewRequest。
# ============================================================================

async def list_reuse_suggestions(
    db, *, status: str | None = None, page: int = 1, size: int = 20,
) -> tuple[int, list]:
    """相似题复用建议审核队列列表（按创建时间倒序）."""
    from sqlalchemy import func, select

    from tag_agent.models import ReuseSuggestion

    count_stmt = select(func.count()).select_from(ReuseSuggestion)
    if status:
        count_stmt = count_stmt.where(ReuseSuggestion.status == status)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = select(ReuseSuggestion).order_by(ReuseSuggestion.created_at.desc())
    if status:
        stmt = stmt.where(ReuseSuggestion.status == status)
    offset = max(0, (page - 1) * size)
    rows = (await db.execute(stmt.offset(offset).limit(size))).scalars().all()
    return total, list(rows)


async def review_reuse_suggestion(
    db,
    *,
    suggestion_id: str,
    action: str,
    admin_id: str,
    admin_note: str = "",
    reject_reason: str = "",
) -> dict:
    """审核单条相似题复用建议.

    action=approve：用模板骨架 + slot_map 渲染复用产物，覆盖目标题 teaching_data.json（写 reuse_info 溯源）。
    action=reject ：仅记录，不落地；必须填写 reject_reason。全程留痕。
    """
    import logging
    from datetime import datetime
    from sqlalchemy import select

    from tag_agent.models import ReuseSuggestion, ReuseSuggestionStatus

    logger = logging.getLogger(__name__)
    sug = (
        await db.execute(select(ReuseSuggestion).where(ReuseSuggestion.id == suggestion_id))
    ).scalar_one_or_none()
    if sug is None:
        raise ValueError(f"复用建议不存在: {suggestion_id}")

    action = (action or "").strip()
    if action not in ("approve", "reject"):
        raise ValueError(f"无效的审核动作: {action}")
    prev_status = sug.status

    if action == "reject":
        if not (reject_reason or "").strip():
            raise ValueError("驳回必须填写驳回原因")
        sug.status = ReuseSuggestionStatus.REJECTED
        sug.reject_reason = (reject_reason or "").strip()
        rendered = False
    else:
        # 渲染复用产物（覆盖目标题）。失败则降级，提示管理员。
        from tag_agent.reuse import render_reuse
        decision = {
            "template_task_id": sug.template_task_id,
            "method_signature": sug.method_signature,
            "slot_map": sug.slot_map or [],
            "confidence": sug.confidence,
            "mode": sug.mode or "L1",
        }
        try:
            result = await render_reuse(
                decision, sug.task_id, sug.question_text or "", sug.title or "", admin_id,
            )
            rendered = bool(result)
        except Exception as e:  # noqa: BLE001
            logger.exception("[复用] 渲染复用产物失败: %s", e)
            result = None
            rendered = False
        if not rendered:
            raise RuntimeError("复用渲染失败（模板骨架缺失或占位符残留），请改用正常生成或换模板")
        sug.status = ReuseSuggestionStatus.APPROVED

    sug.reviewed_by = admin_id
    sug.reviewed_at = datetime.utcnow()
    sug.admin_note = admin_note
    sug.review_history = (sug.review_history or []) + [{
        "from": prev_status,
        "to": sug.status,
        "action": action,
        "by": admin_id,
        "at": datetime.utcnow().isoformat(),
    }]
    await db.commit()
    await db.refresh(sug)
    return {"id": sug.id, "status": sug.status, "rendered": rendered}


async def list_pattern_suggestions(
    db, *, status: str | None = None, page: int = 1, size: int = 20,
) -> tuple[int, list]:
    """题型提示词沉淀审核队列列表（按创建时间倒序）."""
    from sqlalchemy import func, select

    from tag_agent.models import PatternSuggestion

    count_stmt = select(func.count()).select_from(PatternSuggestion)
    if status:
        count_stmt = count_stmt.where(PatternSuggestion.status == status)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = select(PatternSuggestion).order_by(PatternSuggestion.created_at.desc())
    if status:
        stmt = stmt.where(PatternSuggestion.status == status)
    offset = max(0, (page - 1) * size)
    rows = (await db.execute(stmt.offset(offset).limit(size))).scalars().all()
    return total, list(rows)


async def review_pattern_suggestion(
    db,
    *,
    suggestion_id: str,
    action: str,
    admin_id: str,
    admin_note: str = "",
    reject_reason: str = "",
) -> dict:
    """审核单条题型提示词沉淀.

    action=approve：把草稿写入 prompt/animation/scene_patterns/50_pattern_{key}.md（key 由 method_signature 派生）。
    action=reject ：仅记录，不落地；必须填写 reject_reason。
    """
    import logging
    import re as _re
    from datetime import datetime
    from pathlib import Path
    from sqlalchemy import select

    from tag_agent.models import PatternSuggestion, PatternSuggestionStatus

    logger = logging.getLogger(__name__)
    sug = (
        await db.execute(select(PatternSuggestion).where(PatternSuggestion.id == suggestion_id))
    ).scalar_one_or_none()
    if sug is None:
        raise ValueError(f"题型提示词建议不存在: {suggestion_id}")

    action = (action or "").strip()
    if action not in ("approve", "reject"):
        raise ValueError(f"无效的审核动作: {action}")
    prev_status = sug.status

    written_path = None
    if action == "reject":
        if not (reject_reason or "").strip():
            raise ValueError("驳回必须填写驳回原因")
        sug.status = PatternSuggestionStatus.REJECTED
        sug.reject_reason = (reject_reason or "").strip()
    else:
        # 写入 scene_patterns 正式文件（派生 key）
        sig = (sug.method_signature or "").strip()
        key = _re.sub(r"[^0-9a-zA-Z_一-鿿]+", "_", sig) or "auto"
        key = key.strip("_")[:60] or "auto"
        scene_dir = Path(__file__).resolve().parent.parent / "prompt" / "animation" / "scene_patterns"
        scene_dir.mkdir(parents=True, exist_ok=True)
        written_path = scene_dir / f"50_pattern_{key}.md"
        header = (
            f"# 题型提示词（自动沉淀 · method_signature={sig}）\n\n"
            f"> 来源最佳产物：{sug.source_task_id or ''}\n> 审核人：{admin_id}\n> 审核时间：{datetime.utcnow().isoformat()}\n\n"
        )
        written_path.write_text(header + (sug.draft_markdown or ""), encoding="utf-8")
        sug.status = PatternSuggestionStatus.APPROVED
        logger.info("[复用] 题型提示词已写入 %s", written_path)

    sug.reviewed_by = admin_id
    sug.reviewed_at = datetime.utcnow()
    sug.admin_note = admin_note
    sug.review_history = (sug.review_history or []) + [{
        "from": prev_status,
        "to": sug.status,
        "action": action,
        "by": admin_id,
        "at": datetime.utcnow().isoformat(),
        "written_path": str(written_path) if written_path else None,
    }]
    await db.commit()
    await db.refresh(sug)
    return {"id": sug.id, "status": sug.status, "written_path": str(written_path) if written_path else None}
