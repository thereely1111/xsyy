# -*- coding: utf-8 -*-
"""标签识别智能体 API 路由（一体化版：进程内直调智能体本体）.

智能体本体（orchestrator/agents/service/表）随 xsyy 进程运行，不依赖独立
agent-platform 服务（2026-08-31 重新一体化，适配公网单进程部署）。

Endpoints:
    POST /tag-agent/recognize                    — 识别题目（三场景编排，失败降级 legacy）
    GET  /tag-agent/framework                    — 正式标签库概览
    GET  /tag-agent/pending                      — 预修改提案列表（管理后台，可按状态/操作过滤）
    GET  /tag-agent/pending/{pending_id}         — 预修改提案详情
    POST /tag-agent/pending/{pending_id}/review  — 审核单条（按 operation 应用增/改/删/合并）
    POST /tag-agent/pending/batch-review         — 批量审核（阶段二新增）
    GET  /tag-agent/question-proposals           — 题目标签审核队列（阶段二新增）
    GET  /tag-agent/question-proposals/{id}      — 题目标签建议详情
    POST /tag-agent/question-proposals/{id}/review — 审核题目标签建议（通过后 xsyy 侧写 teachings）
    POST /tag-agent/duplicates/scan              — 全库重复标签扫描（阶段一新增，仅提案）
    POST /tag-agent/duplicates/persist           — 去重提案转合并提案入队列
    GET  /tag-agent/stats                        — 聚合统计
    GET  /tag-agent/health                       — 智能体运行状态
    GET  /tag-agent/recognition-logs             — 识别日志
    GET  /tag-agent/learning-records             — 学习闭环记录
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from admin_auth import require_admin
from database import User
from tag_agent import service as tag_service
from tag_agent.config import get_tag_agent_settings
from tag_agent.db import get_db
from tag_agent.orchestrator import TagAgentOrchestrator
from tag_agent.schemas import (
    BatchReviewRequest,
    PendingQuery,
    QuestionProposalQuery,
    QuestionProposalReviewRequest,
    RecognizeRequest,
    ReviewRequest,
)
from tag_agent.tag_library import TagLibrary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tag-agent", tags=["tag-agent"])

# 模块级单例：模型实例复用；标签库数据可被审核结果就地更新
_library: Optional[TagLibrary] = None
_orchestrator: Optional[TagAgentOrchestrator] = None


def get_library() -> TagLibrary:
    global _library
    if _library is None:
        _library = TagLibrary.load(get_tag_agent_settings())
    return _library


def get_orchestrator() -> TagAgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TagAgentOrchestrator(get_library(), get_tag_agent_settings())
    return _orchestrator


# ── 识别 ─────────────────────────────────────────────────────────────────────


@router.post("/recognize")
async def recognize(
    body: RecognizeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """识别题目并执行三场景分支.

    返回结构含 knowledge_tags（tag_source/pending_tag_id/temporary_use 等字段），
    宿主应用据此写入题目元数据。识别或落库失败时降级到 xsyy 原提示词模型（legacy）。
    """
    orchestrator = get_orchestrator()

    async def pending_provider(domain: str, grade: str, chapter: str) -> list[str]:
        return await tag_service.list_pending_names(db, domain, grade, chapter)

    creator_id = body.creator_id or getattr(user, "user_id", "admin")
    try:
        outcome = await orchestrator.recognize(
            body.question,
            question_id=body.question_id,
            creator_id=creator_id,
            pending_name_provider=pending_provider,
        )
        return await tag_service.persist_recognition(
            db,
            question=body.question,
            outcome=outcome,
            question_id=body.question_id,
            creator_id=creator_id,
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("智能体识别失败，回退到原提示词模型")
        try:
            from knowledge_tag_injector import inject_knowledge_tags_full

            legacy = await inject_knowledge_tags_full(body.question)
            if not legacy:
                raise RuntimeError("原提示词模型未返回识别结果")
            return {
                "knowledge_tags": legacy.get("primary"),
                "second_tag": legacy.get("second"),
                "_meta": {
                    "engine": "legacy_fallback",
                    "fallback_reason": str(e),
                    **(legacy.get("_meta") or {}),
                },
            }
        except Exception as fallback_error:  # noqa: BLE001
            logger.exception("智能体和原提示词模型均识别失败")
            raise HTTPException(
                status_code=500,
                detail=f"智能体识别失败，保底模型也失败: {fallback_error}",
            ) from fallback_error


# ── 正式标签库概览 ───────────────────────────────────────────────────────────


@router.get("/framework")
async def get_framework(
    user: User = Depends(require_admin),
) -> dict:
    """正式标签库概览（知识域/年级/章/单元/知识点标签统计）."""
    library = get_library()
    return {
        "source": library.source,
        "domains": library.list_domains(),
        "grades": library.list_grades(),
        "total_main_tags": len({info["chapter"] for info in library.tag_info.values()}),
        "total_sub_tags": len(library.tag_info),
    }


# ── 预加入标签（管理后台审核入口，方案"七.1"）──────────────────────────────


@router.get("/pending")
async def list_pending(
    q: PendingQuery = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """预修改提案列表（管理后台审核入口，可按状态/操作类型过滤）. """
    total, items = await tag_service.list_pending(
        db, status=q.status, operation=q.operation, page=q.page, size=q.size,
    )
    return {"total": total, "items": [p.to_dict() for p in items]}


@router.get("/pending/{pending_id}")
async def get_pending_detail(
    pending_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """预修改提案详情."""
    pending = await tag_service.get_pending(db, pending_id)
    if pending is None:
        raise HTTPException(status_code=404, detail=f"预修改提案不存在: {pending_id}")
    return pending.to_dict()


@router.post("/pending/{pending_id}/review")
async def review_pending(
    pending_id: str,
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """审核单条预修改提案（仅管理员，方案"七"，阶段二按 operation 应用）.

    动作：
      - approve            通过，按提案 operation 应用（add 写入 / modify 更新 /
                            delete 硬删除(需 confirmed=true) / merge 合并）
      - approve_modified   修改后通过（需传修改后的 domain/grade/chapter/tag_name/keywords）
      - merge              合并到已有标签（需传 merged_to_tag）
      - reject             驳回
    返回 reference_updates，宿主应用据此同步题目引用。
    """
    modified = None
    if body.action == "approve_modified":
        modified = {
            "domain": body.domain,
            "grade": body.grade,
            "chapter": body.chapter,
            "tag_name": body.tag_name,
            "keywords": body.keywords,
        }
    try:
        return await tag_service.review_pending(
            db,
            get_library(),
            pending_id=pending_id,
            action=body.action,
            admin_id=user.user_id,
            admin_note=body.admin_note,
            reject_reason=body.reject_reason,
            modified=modified,
            merged_to_tag=body.merged_to_tag,
            confirmed=body.confirmed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/pending/batch-review")
async def batch_review_pending(
    body: BatchReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """批量审核预修改提案（阶段二：管理员勾选多条一次通过/驳回/合并）."""
    try:
        return await tag_service.batch_review_pending(
            db,
            get_library(),
            pending_ids=body.pending_ids,
            action=body.action,
            admin_id=user.user_id,
            admin_note=body.admin_note,
            merged_to_tag=body.merged_to_tag,
            confirmed=body.confirmed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── 题目标签审核队列（阶段二：题目级标签全人工审核）────────────────────────


@router.get("/question-proposals")
async def list_question_proposals(
    q: QuestionProposalQuery = Depends(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """题目标签审核队列列表（管理后台审核入口）. """
    total, items = await tag_service.list_question_proposals(
        db, status=q.status, page=q.page, size=q.size,
    )
    return {"total": total, "items": [p.to_dict() for p in items]}


@router.get("/question-proposals/{proposal_id}")
async def get_question_proposal_detail(
    proposal_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """题目标签建议详情."""
    prop = await tag_service.get_question_proposal(db, proposal_id)
    if prop is None:
        raise HTTPException(status_code=404, detail=f"题目标签建议不存在: {proposal_id}")
    return prop.to_dict()


@router.post("/question-proposals/{proposal_id}/review")
async def review_question_proposal(
    proposal_id: str,
    body: QuestionProposalReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """审核题目标签建议（approve / approve_modified / reject）.

    审核通过后返回 knowledge_tags；一体化部署下**自动应用**到
    teachings.knowledge_tags（题目级标签全人工审核的宿主侧落地）。
    """
    modified = None
    if body.action == "approve_modified":
        modified = {
            "domain": body.domain,
            "grade": body.grade,
            "chapter": body.chapter,
            "sub_tags": body.sub_tags,
        }
    try:
        result = await tag_service.review_question_proposal(
            db,
            proposal_id=proposal_id,
            action=body.action,
            admin_id=user.user_id,
            admin_note=body.admin_note,
            reject_reason=body.reject_reason,
            modified=modified,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # ── 宿主钩子：审核通过 → 应用写 teachings（题目级标签落地）────────
    if result.get("applied") and result.get("knowledge_tags"):
        try:
            from tag_agent.question_queue import apply_knowledge_tags_to_teaching
            from database import SessionLocal
            from database import Teaching
            sync_db = SessionLocal()
            try:
                teaching = sync_db.query(Teaching).filter(
                    Teaching.task_id == result.get("question_id")
                ).first()
                applied = apply_knowledge_tags_to_teaching(
                    teaching,
                    result.get("knowledge_tags"),
                    task_id=result.get("question_id", proposal_id),
                )
                if applied:
                    sync_db.commit()
                    result["applied_to_teaching"] = True
            finally:
                sync_db.close()
        except Exception as e:  # noqa: BLE001
            logger.warning("题目审核结果应用失败: %s", e)
            result["applied_to_teaching"] = False
    # ── 宿主钩子：由"已通过"改判"驳回" → 标记题目待重新识别 ────────
    elif body.action == "reject" and result.get("prev_applied"):
        try:
            from database import SessionLocal, Teaching
            sync_db = SessionLocal()
            try:
                teaching = sync_db.query(Teaching).filter(
                    Teaching.task_id == result.get("question_id")
                ).first()
                if teaching is not None:
                    teaching.knowledge_tags = {
                        "tag_source": "official",
                        "pending_review_status": "rejected",
                        "needs_retag": True,
                        "created_by_agent": False,
                        "rejected_reason": body.reject_reason or "",
                    }
                    try:
                        meta = teaching.metadata
                        if isinstance(meta, dict):
                            meta["knowledge_tags"] = teaching.knowledge_tags
                            meta["tag_review_status"] = "rejected"
                            teaching.metadata = meta
                    except Exception:  # noqa: BLE001
                        pass
                    sync_db.commit()
                    result["reverted_teaching"] = True
            finally:
                sync_db.close()
        except Exception as e:  # noqa: BLE001
            logger.warning("题目标签驳回回退失败: %s", e)

    return result


# ── 去重扫描（阶段一 DedupAgent 的 API 入口）───────────────────────────────


@router.post("/duplicates/scan")
async def scan_duplicates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """触发全库重复标签扫描（仅提案，不直接删库；结果需管理员审核）."""
    orchestrator = get_orchestrator()
    try:
        proposals = await orchestrator.scan_duplicates(use_llm_confirm=True)
    except Exception as e:  # noqa: BLE001
        logger.exception("去重扫描失败")
        raise HTTPException(status_code=500, detail=f"去重扫描失败: {e}") from e
    return {
        "total": len(proposals),
        "items": [p.to_dict() for p in proposals],
    }


@router.post("/duplicates/persist")
async def persist_duplicates(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """把去重扫描结果写入预修改审核队列（operation=merge，阶段三）.

    重新扫描并落库为「合并提案」，管理员在审核页确认后执行合并；
    已存在同目标待审提案的自动跳过（查重）。
    """
    orchestrator = get_orchestrator()
    try:
        proposals = await orchestrator.scan_duplicates(use_llm_confirm=True)
        records = await tag_service.persist_duplicate_proposals(
            db, proposals, created_by=user.user_id,
        )
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("去重提案落库失败")
        raise HTTPException(status_code=500, detail=f"去重提案落库失败: {e}") from e
    return {
        "scanned": len(proposals),
        "created": len(records),
        "items": [r.to_dict() for r in records],
    }


# ── 监控统计（阶段五）─────────────────────────────────────────────────────


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """聚合统计：识别质量 + 审核闭环（监控面板数据源）. """
    return await tag_service.get_stats(db)


# ── 健康检查（管理后台智能体运行监视器）───────────────────────────────────


@router.get("/health")
async def tag_agent_health(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """智能体运行状态检查：模型配置 / 标签库 / 数据库连通性.

    返回 status=ok（全正常）/ degraded（可降级运行）/ error（关键项故障）。
    """
    from tag_agent import db as tag_db

    checks: dict[str, dict] = {}

    # 1) 模型配置（与项目统一出口 kimi_config 同步）
    from kimi_config import get_api_key, get_active_model, get_base_url

    checks["model"] = {
        "ok": bool(get_api_key()),
        "detail": f"{get_active_model()} @ {get_base_url()}"
        if get_api_key() else "缺少 KIMI_API_KEY",
    }

    # 2) 标签库数据源（惰性加载，可能触发远程库读取）
    try:
        library = get_library()
        checks["library"] = {
            "ok": library is not None and len(getattr(library, "tag_info", {})) > 0,
            "detail": f"source={library.source}，标签数={len(library.tag_info)}" if library else "标签库为空",
        }
    except Exception as e:  # noqa: BLE001
        checks["library"] = {"ok": False, "detail": f"标签库加载失败: {e}"}

    # 3) 数据库连通（查询一张表）
    try:
        total, _ = await tag_service.list_pending(db, status="pending", page=1, size=1)
        checks["database"] = {"ok": True, "detail": f"待审提案 {total} 条"}
    except Exception as e:  # noqa: BLE001
        checks["database"] = {"ok": False, "detail": f"数据库异常: {e}"}

    # 4) 编排器可初始化（模型实例构建）
    try:
        orchestrator = get_orchestrator()
        checks["orchestrator"] = {"ok": True, "detail": f"{orchestrator._agents.__len__() if hasattr(orchestrator, '_agents') else 0} agents 惰性待命"}
    except Exception as e:  # noqa: BLE001
        checks["orchestrator"] = {"ok": False, "detail": f"编排器初始化失败: {e}"}

    ok_count = sum(1 for c in checks.values() if c.get("ok"))
    status = "ok" if ok_count == len(checks) else ("degraded" if ok_count >= 2 else "error")
    return {"status": status, "checks": checks}


# ── 识别日志 / 学习记录 ─────────────────────────────────────────────────────


@router.get("/recognition-logs")
async def list_recognition_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    total, items = await tag_service.list_recognition_logs(db, page=page, size=size)
    return {"total": total, "items": [x.to_dict() for x in items]}


@router.get("/learning-records")
async def list_learning_records(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    total, items = await tag_service.list_learning_records(db, page=page, size=size)
    return {"total": total, "items": [x.to_dict() for x in items]}


@router.delete("/learning-records")
async def delete_learning_records(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids 必须为非空数组")
    if not all(isinstance(i, str) and i for i in ids):
        raise HTTPException(status_code=400, detail="ids 元素必须为非空字符串")
    deleted = await tag_service.delete_learning_records(db, ids=ids)
    return {"deleted": deleted}

# ============================================================================
# P1.5 补丁：插入到 backend/tag_agent/router.py
# 插入位置：紧贴 `batch_review_pending` 路由（约 line 241）之后，作为独立代码块。
# 作用：标签增强建议审核队列的列表 + 审核接口（均 require_admin）。
# 合并方式：把下面整段粘贴到 router.py 的合适位置（函数体内，与现有路由同级）。
# 依赖：schemas.py 需补 LabelSuggestionQuery / LabelSuggestionReviewRequest（见 schemas.py.add.txt）。
# ============================================================================

# ── 标签增强建议（P1.5：管理员改标签自动提炼可泛化强关键词）─────────────────
from tag_agent.schemas import LabelSuggestionQuery, LabelSuggestionReviewRequest  # noqa: E402


@router.get("/label-suggestions")
async def list_label_suggestions(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """标签增强建议审核队列（管理后台「标签增强建议」标签页）.

    展示：来源题（题干+新旧标签对照）/ 新标签 B / 候选判词+泛化理由 / 干跑命中样例。
    """
    total, items = await tag_service.list_label_suggestions(
        db, status=status, page=page, size=size,
    )
    return {"total": total, "items": [s.to_dict() for s in items]}


@router.post("/label-suggestions/{suggestion_id}/review")
async def review_label_suggestion_endpoint(
    suggestion_id: str,
    body: LabelSuggestionReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """审核单条标签增强建议.

    action=approve：approved_keywords 不传则默认采纳所有“非疑似过窄”候选；
                    传则仅并入指定判词。通过后并入词库 B 的 keywords 并回写。
    action=reject ：必须传 reject_reason。
    """
    try:
        return await tag_service.review_label_suggestion(
            db,
            get_library(),
            suggestion_id=suggestion_id,
            action=body.action,
            admin_id=user.user_id,
            approved_keywords=body.approved_keywords,
            admin_note=body.admin_note,
            reject_reason=body.reject_reason,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
# ============================================================================
# P3 补丁：追加到 backend/tag_agent/router.py 末尾
# 作用：相似题复用建议队列 + 题型提示词沉淀队列 的列表/审核接口（均 require_admin）。
# 合并方式：整段复制到 router.py 末尾即可（与现有路由同级；文件顶部已 import require_admin / User / get_db）。
# 依赖：schemas.py 需补 ReuseSuggestionQuery / ReuseSuggestionReviewRequest / PatternSuggestionQuery / PatternSuggestionReviewRequest。
# ============================================================================

# ── 相似题复用建议（P3：同法异数复用闸门命中后的人工确认队列）─────────────────
from tag_agent.schemas import (  # noqa: E402
    ReuseSuggestionQuery,
    ReuseSuggestionReviewRequest,
    PatternSuggestionQuery,
    PatternSuggestionReviewRequest,
)


@router.get("/reuse-suggestions")
async def list_reuse_suggestions_endpoint(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """相似题复用建议审核队列（管理后台「复用建议」标签页）.

    展示：新题（题干+标题）/ 模板题对照 / 命中理由 / slot_map 数据槽映射 / 置信度。
    """
    total, items = await tag_service.list_reuse_suggestions(
        db, status=status, page=page, size=size,
    )
    return {"total": total, "items": [s.to_dict() for s in items]}


@router.post("/reuse-suggestions/{suggestion_id}/review")
async def review_reuse_suggestion_endpoint(
    suggestion_id: str,
    body: ReuseSuggestionReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """审核单条相似题复用建议.

    action=approve：用模板骨架 + slot_map 渲染复用产物，覆盖目标题（写 reuse_info 溯源）。
    action=reject ：必须传 reject_reason。
    """
    try:
        return await tag_service.review_reuse_suggestion(
            db,
            suggestion_id=suggestion_id,
            action=body.action,
            admin_id=user.user_id,
            admin_note=body.admin_note,
            reject_reason=body.reject_reason,
        )
    except (ValueError, RuntimeError) as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/pattern-suggestions")
async def list_pattern_suggestions_endpoint(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """题型提示词沉淀审核队列（管理后台「题型提示词」标签页）."""
    total, items = await tag_service.list_pattern_suggestions(
        db, status=status, page=page, size=size,
    )
    return {"total": total, "items": [s.to_dict() for s in items]}


@router.post("/pattern-suggestions/{suggestion_id}/review")
async def review_pattern_suggestion_endpoint(
    suggestion_id: str,
    body: PatternSuggestionReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
) -> dict:
    """审核单条题型提示词沉淀.

    action=approve：草稿写入 prompt/animation/scene_patterns/50_pattern_{key}.md 并生效。
    action=reject ：必须传 reject_reason。
    """
    try:
        return await tag_service.review_pattern_suggestion(
            db,
            suggestion_id=suggestion_id,
            action=body.action,
            admin_id=user.user_id,
            admin_note=body.admin_note,
            reject_reason=body.reject_reason,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
