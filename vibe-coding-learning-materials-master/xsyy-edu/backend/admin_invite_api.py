"""
后台「邀请与额度管理」只读视图接口（PRD 3.4 的 ①邀请关系 + ②额度明细）。

- 全部端点挂在 require_admin 之下，匿名 / 非管理员返回 401 / 403。
- 仅查询 + 导出，绝不触碰额度写逻辑（手动发放走 _admin_add_balance，本模块不调用）。
- 复用 invite_quota_api 的聚合函数（里程碑 / 邀请信息）与 database.models，保持单一数据源。
- 大数据量采用分页 / 流式（StreamingResponse），不一次性全表拉内存。
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import (
    InviteRelation,
    QuotaGrant,
    User,
    get_db,
)
from admin_auth import require_admin
# 复用既有邀请聚合函数与配置读取，避免重复实现里程碑 / 有效期规则
from invite_quota_api import _build_invite_info, _ensure_invite_progress, _get_config_int

router = APIRouter(prefix="/api/admin", tags=["admin-invite-quota"])


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """统一 UTC 时间字符串输出。"""
    return (dt.isoformat() + "Z") if dt else None


def _mask_phone(phone: Optional[str]) -> str:
    """手机号脱敏：138****1120。"""
    if not phone or len(phone) < 7:
        return phone or "-"
    return phone[:3] + "****" + phone[-4:]


def _resolve_user(db: Session, key: str) -> Optional[User]:
    """按 user_id / username / invite_code 三选一解析用户。"""
    if not key or not key.strip():
        return None
    key = key.strip()
    return (
        db.query(User)
        .filter(
            (User.user_id == key)
            | (User.username == key)
            | (User.invite_code == key)
        )
        .first()
    )


@router.get("/invite/stats")
async def admin_invite_stats(
    user_id: str = "",
    page: int = 1,
    size: int = 20,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """单个用户的邀请与额度概览：邀请数 / 累计获得额度 / 本月邀请所得 / 里程碑进度 / 被邀请人列表。

    page / size 用于被邀请人列表分页；统计与里程碑仍按单用户聚合。
    """
    user = _resolve_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    progress = _ensure_invite_progress(db, user.user_id)
    info = _build_invite_info(db, user, progress)

    total_granted = int(
        db.query(func.coalesce(func.sum(QuotaGrant.amount), 0))
        .filter(QuotaGrant.user_id == user.user_id)
        .scalar()
        or 0
    )

    # 被邀请人列表（按邀请关系创建时间倒序，支持分页）
    page = max(1, int(page))
    size = min(max(1, int(size)), 100)
    rel_query = db.query(InviteRelation).filter(
        InviteRelation.inviter_user_id == user.user_id
    )
    total_invitees = rel_query.count()
    relations = (
        rel_query.order_by(InviteRelation.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    invited_user_ids = [r.invited_user_id for r in relations]
    users_map: Dict[str, User] = {}
    if invited_user_ids:
        users_map = {
            u.user_id: u
            for u in db.query(User).filter(User.user_id.in_(invited_user_ids)).all()
        }

    # 这批被邀请人对应的邀请奖励发放记录（发给邀请人的 invite_reward，source_user_id 指向被邀请人）
    reward_map: Dict[str, QuotaGrant] = {}
    if invited_user_ids:
        rewards = (
            db.query(QuotaGrant)
            .filter(
                QuotaGrant.user_id == user.user_id,
                QuotaGrant.grant_type == "invite_reward",
                QuotaGrant.source_user_id.in_(invited_user_ids),
            )
            .all()
        )
        reward_map = {r.source_user_id: r for r in rewards}

    invitees = []
    monthly_granted = int(info.get("monthlyGranted") or 0)
    for r in relations:
        invited = users_map.get(r.invited_user_id)
        if not invited:
            continue
        reward = reward_map.get(r.invited_user_id)
        invitees.append(
            {
                "userId": invited.user_id,
                "username": invited.username,
                "phone": _mask_phone(invited.phone),
                "registeredAt": _format_datetime(invited.created_at),
                "inviteCode": user.invite_code,
                "relationStatus": "已绑定·生效",
                "rewardAmount": int(reward.amount) if reward else 0,
                "rewardGrantedAt": _format_datetime(reward.created_at) if reward else None,
                "inviterMonthlyCount": monthly_granted,
            }
        )

    return {
        "success": True,
        "userId": user.user_id,
        "username": user.username,
        "inviteCode": info.get("inviteCode"),
        "invitedCount": info.get("invitedCount"),
        "monthlyGranted": monthly_granted,
        "totalQuotaGranted": total_granted,
        "milestones": info.get("milestones", []),
        "invitees": invitees,
        "inviteeTotal": total_invitees,
        "inviteePage": page,
        "inviteeSize": size,
    }


def _grant_status(g: QuotaGrant, now: datetime) -> str:
    """根据剩余次数与过期时间计算状态。"""
    if g.remaining is not None and int(g.remaining) <= 0:
        return "exhausted"
    if g.expire_at and g.expire_at < now:
        return "expired"
    return "active"


def _grant_rule(g: QuotaGrant, db: Session) -> str:
    """根据额度类型与系统配置生成规则说明。"""
    if g.grant_type == "admin":
        return "管理员补发"

    rule_map = {
        "new_user_gift": ("new_user_gift_quota", "new_user_gift_valid_days", "注册赠"),
        "invited_extra": ("invited_extra_quota", "invited_extra_valid_days", "被邀额外"),
        "invite_reward": ("invite_reward_quota", "invite_reward_valid_days", "邀请奖励"),
    }
    qkey, dkey, label = rule_map.get(g.grant_type, (None, None, g.grant_type))
    amount = int(g.amount or 0)
    days = _get_config_int(db, dkey) if dkey else 0
    parts = [f"{label} {amount} 次"]
    if days:
        parts.append(f"{days} 天有效期")
    if g.grant_type == "invite_reward":
        cap = _get_config_int(db, "invite_reward_monthly_cap")
        if cap:
            parts.append(f"当月上限 {cap} 次")
    return "；".join(parts)


@router.get("/quota/grants")
async def admin_quota_grants(
    user_id: str = "",
    grant_type: str = "",
    status: str = "",
    page: int = 1,
    size: int = 20,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """某用户的额度发放明细，按 grant_type / status 筛选 + 分页，返回状态与规则说明。"""
    user = _resolve_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    page = max(1, int(page))
    size = min(max(1, int(size)), 100)

    query = db.query(QuotaGrant).filter(QuotaGrant.user_id == user.user_id)
    if grant_type:
        query = query.filter(QuotaGrant.grant_type == grant_type)

    status = (status or "").strip().lower()
    # 单用户额度批次通常不多，先全量拉取以便做状态筛选与汇总；如数据量大可改成分层查询
    rows = query.order_by(QuotaGrant.created_at.desc()).all()
    now = datetime.utcnow()

    filtered_rows = [g for g in rows if not status or _grant_status(g, now) == status]
    total = len(filtered_rows)
    page_rows = filtered_rows[(page - 1) * size : page * size]

    active_count = sum(1 for g in rows if _grant_status(g, now) == "active")
    expired_count = len(rows) - active_count

    items: List[Dict[str, Any]] = [
        {
            "id": g.id,
            "grantType": g.grant_type,
            "amount": int(g.amount or 0),
            "remaining": int(g.remaining or 0),
            "sourceUserId": g.source_user_id,
            "grantedAt": _format_datetime(g.created_at),
            "expireAt": _format_datetime(g.expire_at),
            "status": _grant_status(g, now),
            "rule": _grant_rule(g, db),
        }
        for g in page_rows
    ]

    return {
        "success": True,
        "userId": user.user_id,
        "total": total,
        "page": page,
        "size": size,
        "items": items,
        "summary": {
            "activeCount": active_count,
            "expiredCount": expired_count,
        },
    }


@router.get("/invite/export")
async def admin_invite_export(
    user_id: str = "",
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """导出邀请关系 + 额度汇总 CSV（流式，避免大表占内存）。

    传入 user_id 时只导出该用户的下游邀请关系，缺省导出全量。
    列：邀请人 / 邀请人ID / 被邀请人 / 被邀请人ID / 邀请时间 / 被邀请人累计获得额度。
    """
    rel_query = db.query(InviteRelation)
    if user_id:
        user = _resolve_user(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        rel_query = rel_query.filter(InviteRelation.inviter_user_id == user.user_id)

    relations = rel_query.order_by(InviteRelation.created_at.desc()).all()

    user_ids: set = set()
    for r in relations:
        user_ids.add(r.inviter_user_id)
        user_ids.add(r.invited_user_id)

    users_map = {
        u.user_id: u
        for u in db.query(User).filter(User.user_id.in_(list(user_ids))).all()
    }

    grant_sums: Dict[str, int] = {}
    if user_ids:
        sum_rows = (
            db.query(
                QuotaGrant.user_id,
                func.coalesce(func.sum(QuotaGrant.amount), 0),
            )
            .filter(QuotaGrant.user_id.in_(list(user_ids)))
            .group_by(QuotaGrant.user_id)
            .all()
        )
        grant_sums = {uid: int(s) for uid, s in sum_rows}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["邀请人", "邀请人ID", "被邀请人", "被邀请人ID", "邀请时间", "被邀请人累计获得额度"]
    )
    for r in relations:
        inviter = users_map.get(r.inviter_user_id)
        invited = users_map.get(r.invited_user_id)
        writer.writerow([
            inviter.username if inviter else "",
            r.inviter_user_id,
            invited.username if invited else "",
            r.invited_user_id,
            (r.created_at.isoformat() + "Z") if r.created_at else "",
            grant_sums.get(r.invited_user_id, 0),
        ])

    # UTF-8 BOM 保证 Excel 正确识别中文
    content = "﻿" + buffer.getvalue()
    headers = {
        "Content-Disposition": "attachment; filename=invite_quota_export.csv"
    }
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get("/quota/export")
async def admin_quota_export(
    user_id: str = "",
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """导出某用户的额度发放明细 CSV（流式）。

    列：批次ID / 用户 / 额度类型 / 数量 / 剩余 / 来源用户 / 发放时间 / 过期时间 / 状态 / 规则。
    """
    user = _resolve_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    rows = (
        db.query(QuotaGrant)
        .filter(QuotaGrant.user_id == user.user_id)
        .order_by(QuotaGrant.created_at.desc())
        .all()
    )
    now = datetime.utcnow()

    source_ids = {g.source_user_id for g in rows if g.source_user_id}
    users_map: Dict[str, User] = {}
    if source_ids:
        users_map = {
            u.user_id: u
            for u in db.query(User).filter(User.user_id.in_(list(source_ids))).all()
        }

    GRANT_LABELS = {
        "new_user_gift": "注册赠礼",
        "invited_extra": "被邀额外",
        "invite_reward": "邀请奖励",
        "admin": "管理员补发",
    }
    STATUS_LABELS = {
        "active": "生效中",
        "expired": "已过期",
        "exhausted": "已用完",
    }

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["批次ID", "用户", "额度类型", "数量", "剩余", "来源用户", "发放时间", "过期时间", "状态", "规则体现"]
    )
    for g in rows:
        source_user = users_map.get(g.source_user_id)
        writer.writerow([
            g.id,
            user.username,
            GRANT_LABELS.get(g.grant_type, g.grant_type),
            int(g.amount or 0),
            int(g.remaining or 0),
            source_user.username if source_user else (g.source_user_id or "-"),
            _format_datetime(g.created_at),
            _format_datetime(g.expire_at),
            STATUS_LABELS.get(_grant_status(g, now), _grant_status(g, now)),
            _grant_rule(g, db),
        ])

    content = "﻿" + buffer.getvalue()
    headers = {
        "Content-Disposition": f"attachment; filename=quota_export_{user.user_id}.csv"
    }
    return StreamingResponse(
        iter([content]),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get("/invite/list")
async def admin_invite_list(
    keyword: str = "",
    page: int = 1,
    size: int = 20,
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """全量邀请关系分页列表，可按用户名 / user_id / 邀请码关键字过滤。

    与 /invite/stats 的区别：不要求先定位到单个用户，打开页面即可浏览全部邀请记录。
    """
    page = max(1, int(page))
    size = min(max(1, int(size)), 100)

    query = db.query(InviteRelation)
    keyword = (keyword or "").strip()
    if keyword:
        matched_ids = [
            row[0]
            for row in db.query(User.user_id)
            .filter(
                or_(
                    User.user_id == keyword,
                    User.invite_code == keyword,
                    User.username.contains(keyword),
                )
            )
            .all()
        ]
        if not matched_ids:
            return {"success": True, "total": 0, "page": page, "size": size, "items": []}
        query = query.filter(
            or_(
                InviteRelation.inviter_user_id.in_(matched_ids),
                InviteRelation.invited_user_id.in_(matched_ids),
            )
        )

    total = query.count()
    relations = (
        query.order_by(InviteRelation.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    # 批量取本页涉及的用户信息，避免逐行查询
    user_ids: set = set()
    for r in relations:
        user_ids.add(r.inviter_user_id)
        user_ids.add(r.invited_user_id)
    users_map: Dict[str, User] = {}
    if user_ids:
        users_map = {
            u.user_id: u
            for u in db.query(User).filter(User.user_id.in_(list(user_ids))).all()
        }

    items = []
    for r in relations:
        inviter = users_map.get(r.inviter_user_id)
        invited = users_map.get(r.invited_user_id)
        items.append(
            {
                "inviterUserId": r.inviter_user_id,
                "inviterUsername": inviter.username if inviter else "-",
                "invitedUserId": r.invited_user_id,
                "invitedUsername": invited.username if invited else "-",
                "createdAt": _format_datetime(r.created_at),
            }
        )

    return {"success": True, "total": total, "page": page, "size": size, "items": items}


@router.get("/invite/summary")
async def admin_invite_summary(
    admin_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """全局概览卡：总邀请人数 / 总发放额度 / 本月新增邀请。"""
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_invited = (
        db.query(func.count(InviteRelation.inviter_user_id)).scalar() or 0
    )
    total_granted = int(
        db.query(func.coalesce(func.sum(QuotaGrant.amount), 0)).scalar() or 0
    )
    month_new = (
        db.query(func.count(InviteRelation.inviter_user_id))
        .filter(InviteRelation.created_at >= month_start)
        .scalar()
        or 0
    )

    return {
        "success": True,
        "totalInvited": int(total_invited),
        "totalQuotaGranted": total_granted,
        "monthNewInvites": int(month_new),
    }
