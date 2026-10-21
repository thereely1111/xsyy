from __future__ import annotations

import calendar
import json
import re
import secrets
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from auth import generate_token, hash_password, verify_token, verify_verification_code, delete_verification_code, create_session_token
from database import (
    AITeachingQA,
    Comment,
    CommentLike,
    CommissionAccount,
    CommissionRecord,
    DeviceBinding,
    DeviceQuota,
    Favorite,
    InviteProgress,
    InviteRelation,
    OfficialInviteCode,
    QuotaGrant,
    SystemConfig,
    Teaching,
    TeachingLike,
    Topic,
    User,
    UserQuota,
    UserViewHistory,
    VerificationCode,
    WithdrawalRequest,
    get_db,
)

router = APIRouter(prefix="/api/v2", tags=["auth-v2", "quota", "invite"])
security = HTTPBearer(auto_error=False)


def _get_client_ip(request: Request) -> str:
    """获取客户端 IP，优先使用反向代理头。"""
    cf_ip = request.headers.get("cf-connecting-ip", "")
    if cf_ip:
        return cf_ip.strip()
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip", "")
    if real_ip:
        return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"

OFFICIAL_INVITE_CODE = "XSYY2026"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9\u4e00-\u9fa5]{2,20}$")
INVITE_PATTERN = re.compile(r"^[A-Z]{4}\d{4}$")
# 邀请返利（单级返佣）规则常量。全部可调项存于 system_configs 表，管理员可在后台实时调整
# （活动总控 invite_activity_enabled、额度、首单佣金/续费比例、解冻期、提现门槛、里程碑等）。
NON_WORD_PATTERN = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fa5]+")
DATA_DIR = Path(__file__).resolve().parent.parent / "storage"
INVITE_TREE_MAX_DEPTH = 3  # 邀请关系树展示深度（仅展示用，返佣固定只到一级）


class CheckDeviceBindingRequest(BaseModel):
    deviceId: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    passwordConfirm: str
    inviteCode: str
    deviceId: str
    grade: Optional[str] = None  # 所在年级（1-9，可选）


class LoginPasswordRequest(BaseModel):
    username: str
    password: str
    deviceId: Optional[str] = None


class LoginPhoneRequest(BaseModel):
    phone: str
    code: str
    inviteCode: Optional[str] = None
    deviceId: str


class ValidateInviteRequest(BaseModel):
    inviteCode: str


class WithdrawCommissionRequest(BaseModel):
    amount: int  # 提现金额（单位：分）


class ConsumeRequest(BaseModel):
    deviceId: Optional[str] = None


class GenerationRequest(BaseModel):
    prompt: str
    deviceId: Optional[str] = None


class SearchQuestionRequest(BaseModel):
    query: str
    limit: Optional[int] = 10


def _today_str() -> str:
    return date.today().isoformat()


def _normalize_text(value: str) -> str:
    normalized = NON_WORD_PATTERN.sub("", (value or "").lower())
    return normalized.strip()


def _text_tokenize(value: str) -> List[str]:
    compact = _normalize_text(value)
    if not compact:
        return []
    if len(compact) <= 2:
        return [compact]
    return [compact[index : index + 2] for index in range(len(compact) - 1)]


def _score_question(query_text: str, candidate_text: str) -> float:
    query_norm = _normalize_text(query_text)
    candidate_norm = _normalize_text(candidate_text)
    if not query_norm or not candidate_norm:
        return 0.0

    if query_norm in candidate_norm:
        return 1.0

    query_tokens = set(_text_tokenize(query_norm))
    candidate_tokens = set(_text_tokenize(candidate_norm))
    if not query_tokens or not candidate_tokens:
        return 0.0

    overlap = len(query_tokens & candidate_tokens)
    return overlap / len(query_tokens)


def _load_storage_candidates(limit: int = 300) -> List[Dict[str, str]]:
    if not DATA_DIR.exists():
        return []

    candidates: List[Dict[str, str]] = []
    try:
        for task_dir in sorted(DATA_DIR.iterdir(), key=lambda entry: entry.name, reverse=True):
            if not task_dir.is_dir():
                continue
            metadata_path = task_dir / "metadata.json"
            if not metadata_path.exists():
                continue

            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                continue

            text = str(metadata.get("question") or metadata.get("title") or "").strip()
            if not text:
                continue

            candidates.append({"taskId": task_dir.name, "question": text})
            if len(candidates) >= limit:
                break
    except Exception:
        return candidates

    return candidates


def _require_valid_device_id(device_id: str) -> str:
    value = (device_id or "").strip()
    if len(value) < 8:
        raise HTTPException(status_code=400, detail="无效的设备ID")
    return value


def _normalize_invite_code(invite_code: str) -> str:
    """统一大小写并去空白；空值返回空串。"""
    return (invite_code or "").strip().upper()


def _is_official_code(db: Session, code: str) -> bool:
    """邀请码是否为「启用中」的官方邀请码（来自 official_invite_codes 表）。

    兼容迁移过渡期：若官方码表尚未初始化（记录数为 0），沿用历史硬编码官方码，
    避免存量注册链接在部署迁移完成前失效。一旦表中存在任何记录，校验即完全以数据库为准。
    """
    if not code:
        return False
    official = db.query(OfficialInviteCode).filter(
        OfficialInviteCode.code == code,
        OfficialInviteCode.is_active == True,
    ).first()
    if official:
        return True
    # 过渡兜底：官方码表尚未建立/为空时，兼容历史硬编码官方码
    if db.query(OfficialInviteCode).count() == 0 and code == OFFICIAL_INVITE_CODE:
        return True
    return False


def _touch_official_code(db: Session, code: str) -> None:
    """官方邀请码被成功使用时，累加使用次数与最近使用时间。"""
    official = db.query(OfficialInviteCode).filter(
        OfficialInviteCode.code == code,
        OfficialInviteCode.is_active == True,
    ).first()
    if official:
        official.used_count = int(official.used_count or 0) + 1
        official.last_used_at = datetime.utcnow()
        db.flush()


def _validate_invite_code_format(db: Session, invite_code: str) -> str:
    code = _normalize_invite_code(invite_code)
    if _is_official_code(db, code):
        return code
    if not INVITE_PATTERN.fullmatch(code):
        raise HTTPException(status_code=400, detail="邀请码格式错误，请输入4位大写字母+4位数字")
    return code


def _find_inviter_by_code(db: Session, invite_code: str) -> Optional[User]:
    code = _validate_invite_code_format(db, invite_code)
    if _is_official_code(db, code):
        return None  # 官方邀请码：不计具体邀请人，仅表示「有效注册」
    inviter = db.query(User).filter(User.invite_code == code).first()
    if not inviter:
        raise HTTPException(status_code=400, detail="邀请码不存在或已失效")
    return inviter


# ==================== 系统配置读取（存于 system_configs 表，后台实时可改） ====================

DEFAULT_CONFIGS: Dict[str, Any] = {
    # ⓪ 活动总控
    "invite_activity_enabled": 1,       # 总开关：0=停发返佣/邀请奖励/被邀额外奖励/里程碑
    "invite_commission_enabled": 1,     # 返佣分发明细开关（灰度）
    # ① 赠送与邀请额度
    "new_user_gift_quota": 8,           # 新用户注册赠送使用额度（次）
    "new_user_gift_valid_days": 7,      # 注册赠送额度有效期（天）
    "invited_extra_quota": 5,           # 经邀请码注册者额外赠送额度（次）
    "invited_extra_valid_days": 30,     # 被邀请人额外赠送额度有效期（天）
    "invite_reward_quota": 5,           # 每成功邀请 1 人，邀请人获得额度（次）
    "invite_reward_valid_days": 30,     # 邀请奖励额度有效期（天）
    "invite_reward_monthly_cap": 30,    # 邀请奖励月度累计上限（次）
    # ② 返佣规则
    "commission_first_fen": {"monthly": 1000, "quarterly": 2500, "yearly": 6000},
    "commission_renewal_pct": 30,       # 续费佣金 = 首单佣金 × 百分比
    "commission_inviter_paid": 1,       # 1=仅已付费邀请人（paid_once=1）；0=任意邀请人
    "commission_freeze_days": 7,        # 佣金解冻期（天）
    # ③ 提现规则
    "withdraw_min_fen": 5000,           # 最低提现金额（分，5000=50 元）
    "withdraw_monthly_times": 2,        # 每月提现次数上限
    # ④ 累计邀请里程碑
    "invite_milestones": [
        {"invited": 3, "days": 7, "label": "7天会员体验"},
        {"invited": 10, "days": 30, "months": 1, "label": "月度会员体验"},
        {"invited": 30, "days": 90, "months": 3, "label": "季度会员体验"},
    ],
    "invite_manual_review_threshold": 50,  # 单账户月度邀请人头数告警阈值
}


def _get_config_str(db: Session, key: str) -> str:
    """从 system_configs 表读取配置原始字符串；缺省时返回内置默认值"""
    row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if row and row.config_value is not None and str(row.config_value).strip() != "":
        return str(row.config_value)
    default = DEFAULT_CONFIGS.get(key)
    return str(default) if default is not None else ""


def _get_config_int(db: Session, key: str) -> int:
    """从 system_configs 表读取整数配置（实时生效）；缺省时返回内置默认值"""
    row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if row and row.config_value is not None and str(row.config_value).strip() != "":
        try:
            return int(row.config_value)
        except (TypeError, ValueError):
            pass
    return int(DEFAULT_CONFIGS.get(key, 0))


def _get_config_json(db: Session, key: str):
    """从 system_configs 表读取 JSON 配置；缺省/解析失败返回内置默认值"""
    row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if row and row.config_value is not None and str(row.config_value).strip() != "":
        try:
            return json.loads(row.config_value)
        except Exception:
            pass
    return DEFAULT_CONFIGS.get(key)


def _ensure_user_quota(db: Session, user_id: str) -> UserQuota:
    quota = db.query(UserQuota).filter(UserQuota.user_id == user_id).first()
    if not quota:
        quota = UserQuota(user_id=user_id, daily_free_used=0, extra_balance=0, last_reset_date=_today_str())
        db.add(quota)
        db.flush()
    return quota


def _activity_enabled(db: Session) -> bool:
    """邀请返利活动总开关：0=停发返佣/邀请奖励/被邀额外奖励/里程碑（注册赠送与官方邀请码不受影响）"""
    return _get_config_int(db, "invite_activity_enabled") == 1


def _grant_quota(db: Session, user_id: str, grant_type: str, amount: int,
                 valid_days: int = 0, source_user_id: Optional[str] = None) -> int:
    """发放一笔赠送额度批次并累加聚合余额；valid_days<=0 表示长期有效。返回发放次数。"""
    amount = int(amount or 0)
    if amount <= 0:
        return 0
    expire_at = None
    if valid_days and valid_days > 0:
        expire_at = datetime.utcnow() + timedelta(days=int(valid_days))
    db.add(QuotaGrant(
        user_id=user_id,
        grant_type=grant_type,
        amount=amount,
        remaining=amount,
        expire_at=expire_at,
        source_user_id=source_user_id,
    ))
    quota = _ensure_user_quota(db, user_id)
    quota.extra_balance = int(quota.extra_balance or 0) + amount
    return amount


def _get_subscription_expire_utc(db: Session, user_id: str) -> Optional[datetime]:
    """用户订阅到期时刻（含已过期的历史订阅），统一转成 UTC naive 与额度域对齐；无订阅记录返回 None。

    会员期获得的赠送额度，有效期从该时刻起重新计算。用订阅记录时刻而非「是否仍有效」判断，
    是为了让「会员结束后才开始计时」在会员到期后依然成立。
    """
    subs = _get_user_subscriptions(db)
    info = subs.get(user_id)
    if not info or not info.get("expire_at"):
        return None
    expire = _parse_expire_at(info["expire_at"])
    if expire is None:
        return None
    return expire.astimezone(timezone.utc).replace(tzinfo=None)


def _effective_expire(grant: QuotaGrant, sub_expire_utc: Optional[datetime]) -> Optional[datetime]:
    """批次实际到期时刻：会员期内发放的批次，有效期顺延到会员到期后重新起算。

    有效天数从 expire_at - created_at 差值还原；用户仍在会员期时（订阅到期时刻在当前之后），
    会员期内批次按此公式永远不会被判过期。
    """
    if grant.expire_at is None or sub_expire_utc is None:
        return grant.expire_at
    if grant.created_at and grant.created_at < sub_expire_utc:
        return sub_expire_utc + (grant.expire_at - grant.created_at)
    return grant.expire_at


def _sync_extra_balance(db: Session, user_id: str) -> int:
    """把 user_quotas.extra_balance 重算为 quota_grants 未过期批次剩余之和（消费/过期清理后调用）。

    求和按「实际到期时刻」（_effective_expire）排除已过期批次：即使过期清理未被触发，
    重算结果也不会把过期额度计入余额。
    """
    quota = _ensure_user_quota(db, user_id)
    sub_expire = _get_subscription_expire_utc(db, user_id)
    now = datetime.utcnow()
    total = 0
    for grant in db.query(QuotaGrant).filter(QuotaGrant.user_id == user_id).all():
        remaining = int(grant.remaining or 0)
        if remaining <= 0:
            continue
        expire = _effective_expire(grant, sub_expire)
        if expire is None or expire >= now:
            total += remaining
    quota.extra_balance = total
    return total


def _purge_expired_grants(db: Session, user_id: str) -> None:
    """把实际到期时刻已过且仍有剩余的批次清零（过期不补、不占用余额）。

    实际到期时刻 = _effective_expire：会员期内发放的批次在会员有效期内不会被判过期。
    """
    now = datetime.utcnow()
    sub_expire = _get_subscription_expire_utc(db, user_id)
    for grant in db.query(QuotaGrant).filter(
        QuotaGrant.user_id == user_id,
        QuotaGrant.expire_at.isnot(None),
        QuotaGrant.remaining > 0,
    ).all():
        expire = _effective_expire(grant, sub_expire)
        if expire is not None and expire < now:
            grant.remaining = 0


def _sorted_active_grants(db: Session, user_id: str):
    """剩余批次按实际到期先后排序（长期 NULL 批次排最后），供 FIFO 消费；内部先做过期清理。"""
    _purge_expired_grants(db, user_id)
    sub_expire = _get_subscription_expire_utc(db, user_id)
    now = datetime.utcnow()
    items = []
    for grant in db.query(QuotaGrant).filter(
        QuotaGrant.user_id == user_id,
        QuotaGrant.remaining > 0,
    ).all():
        expire = _effective_expire(grant, sub_expire)
        if expire is not None and expire < now:
            continue
        items.append((grant, expire))
    items.sort(key=lambda item: (1, now) if item[1] is None else (0, item[1]))
    return items


def _consume_quota(db: Session, user_id: str, amount: int) -> int:
    """批量按实际到期先后 FIFO 消费 amount 次（管理员扣除/对账用），返回实际扣除次数。"""
    amount = int(amount or 0)
    if amount <= 0:
        return 0
    consumed = 0
    for grant, _expire in _sorted_active_grants(db, user_id):
        if consumed >= amount:
            break
        take = min(amount - consumed, int(grant.remaining or 0))
        grant.remaining = int(grant.remaining or 0) - take
        consumed += take
    if consumed:
        _sync_extra_balance(db, user_id)
    return consumed


def _admin_add_balance(db: Session, user_id: str, delta: int) -> int:
    """管理员增减余额（>0 补发长期批次；<0 按 FIFO 扣除）。返回调整后聚合余额。"""
    delta = int(delta or 0)
    _purge_expired_grants(db, user_id)
    current = (
        db.query(func.coalesce(func.sum(QuotaGrant.remaining), 0))
        .filter(QuotaGrant.user_id == user_id)
        .scalar()
    ) or 0
    if delta > 0:
        _grant_quota(db, user_id, "admin", delta, valid_days=0)
    elif delta < 0:
        need = -delta
        if need > current:
            raise HTTPException(status_code=400, detail=f"余额不足，当前余额为 {current}，无法扣除 {need}")
        _consume_quota(db, user_id, need)
    return _sync_extra_balance(db, user_id)


def _consume_one_quota(db: Session, user_id: str) -> bool:
    """FIFO 消费 1 次：优先扣最早到期批次（按实际到期时刻，长期 NULL 批次排最后）。成功返回 True。"""
    items = _sorted_active_grants(db, user_id)
    if not items:
        _sync_extra_balance(db, user_id)
        return False
    grant = items[0][0]
    grant.remaining = int(grant.remaining or 0) - 1
    _sync_extra_balance(db, user_id)
    return True


def _ensure_device_quota(db: Session, device_id: str) -> DeviceQuota:
    quota = db.query(DeviceQuota).filter(DeviceQuota.device_id == device_id).first()
    if not quota:
        quota = DeviceQuota(device_id=device_id, daily_free_used=0, last_reset_date=_today_str())
        db.add(quota)
        db.flush()
    return quota


def _ensure_invite_progress(db: Session, user_id: str) -> InviteProgress:
    progress = db.query(InviteProgress).filter(InviteProgress.user_id == user_id).first()
    if not progress:
        progress = InviteProgress(user_id=user_id, invited_count=0, claimed_targets=[])
        db.add(progress)
        db.flush()
    return progress


def _generate_unique_invite_code(db: Session) -> str:
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    for _ in range(100):
        code = "".join(secrets.choice(letters) for _ in range(4)) + f"{secrets.randbelow(10000):04d}"
        exists = db.query(User).filter(User.invite_code == code).first()
        if not exists:
            return code
    raise HTTPException(status_code=500, detail="邀请码生成失败，请稍后重试")


def _grant_new_user_gift(db: Session, user: User) -> int:
    """新用户注册赠送使用额度（批次账本，数值/有效期在系统配置中可调，默认 8 次 / 7 天）。

    仅首次注册发放；不受邀请返利活动总开关影响（总开关只管返佣/邀请类奖励）。
    """
    quota = _ensure_user_quota(db, user.user_id)
    if not user.first_login_reward_granted:
        reward = _get_config_int(db, "new_user_gift_quota")
        valid_days = _get_config_int(db, "new_user_gift_valid_days")
        granted = _grant_quota(db, user.user_id, "new_user_gift", reward, valid_days=valid_days)
        user.first_login_reward_granted = True
        return granted
    return 0


def _grant_invited_extra(db: Session, invited_user_id: str, inviter_user_id: str) -> int:
    """被邀请人额外赠送额度（默认 5 次 / 30 天）。受活动总开关控制。"""
    if not _activity_enabled(db):
        return 0
    reward = _get_config_int(db, "invited_extra_quota")
    valid_days = _get_config_int(db, "invited_extra_valid_days")
    return _grant_quota(db, invited_user_id, "invited_extra", reward,
                        valid_days=valid_days, source_user_id=inviter_user_id)


# 同 IP 自邀判定阈值：单一 IP 完全一致不再直接判自邀（家庭 WiFi 共享公网 IP 会误伤），
# 改为统计该邀请人已有被邀人中与本 IP 相同的人数，达到阈值才判为批量自邀农场。
SELF_INVITE_IP_THRESHOLD = 3


def _is_suspected_self_invite(db: Session, inviter: User, invited_user_id: str,
                              invited_device_id: str, invited_ip: str) -> bool:
    """自邀请风控：被邀请人的注册设备/注册 IP 与邀请人一致，视为疑似自邀。

    定稿口径：不计入邀请关系、不发任何邀请奖励（注册赠送 8 次仍发）。
    设备维度：被邀设备若已绑定在邀请人名下则命中（强信号，同设备基本同人，硬拦截）。
    IP 维度（阈值化）：不再因「单次 IP 完全一致」直接判自邀（家庭 WiFi 共享公网 IP 会误伤），
        改为统计该邀请人已有被邀人中、注册 IP 与本 IP 相同的人数，达到 SELF_INVITE_IP_THRESHOLD
        才判为批量自邀农场——容忍家庭 1~2 人同 IP，拦批量小号。
    """
    if not inviter:
        return False
    if invited_device_id:
        bound = (
            db.query(DeviceBinding)
            .filter(DeviceBinding.device_id == invited_device_id, DeviceBinding.user_id == inviter.user_id)
            .first()
        )
        if bound:
            return True
    if invited_ip and invited_ip != "unknown":
        same_ip_count = (
            db.query(InviteRelation)
            .join(User, User.user_id == InviteRelation.invited_user_id)
            .filter(InviteRelation.inviter_user_id == inviter.user_id, User.ip_address == invited_ip)
            .count()
        )
        if same_ip_count >= SELF_INVITE_IP_THRESHOLD:
            return True
    return False


def _upsert_invite_relation(db: Session, inviter_user_id: str, invited_user_id: str,
                            invited_device_id: str, invited_ip: str = "") -> bool:
    """建立单级邀请关系并发放邀请奖励。返回是否计为一次有效邀请。

    - 已存在关系则跳过（幂等）；
    - 活动总开关关闭时不发放任何邀请奖励，但关系照常建立（供活动恢复后追溯）；
    - 邀请奖励受月度累计上限控制（quota_grants 按月统计）。
    """
    existed = db.query(InviteRelation).filter(InviteRelation.invited_user_id == invited_user_id).first()
    if existed:
        return False

    # invited_device_id 上有唯一索引；同一设备可注册多个账号（_bind_device_or_fail 放行），
    # 但同一设备只计一次有效邀请，否则再次插入会触发唯一键冲突（1062）导致注册 500。
    if invited_device_id:
        device_used = (
            db.query(InviteRelation)
            .filter(InviteRelation.invited_device_id == invited_device_id)
            .first()
        )
        if device_used:
            return False

    inviter = db.query(User).filter(User.user_id == inviter_user_id).first()
    if _is_suspected_self_invite(db, inviter, invited_user_id, invited_device_id, invited_ip):
        # 疑似自邀请：不计入、不发奖（注册赠送已在注册流程发放，不受影响）
        return False

    db.add(
        InviteRelation(
            inviter_user_id=inviter_user_id,
            invited_user_id=invited_user_id,
            invited_device_id=invited_device_id,
        )
    )
    inviter_progress = _ensure_invite_progress(db, inviter_user_id)
    inviter_progress.invited_count = int(inviter_progress.invited_count or 0) + 1

    if _activity_enabled(db):
        # 邀请有礼：每成功邀请 1 位新用户，邀请人获得固定次数奖励（默认 5 次 / 30 天，可后台配置）
        reward = _get_config_int(db, "invite_reward_quota")
        valid_days = _get_config_int(db, "invite_reward_valid_days")
        monthly_cap = _get_config_int(db, "invite_reward_monthly_cap")
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_granted = (
            db.query(func.coalesce(func.sum(QuotaGrant.amount), 0))
            .filter(
                QuotaGrant.user_id == inviter_user_id,
                QuotaGrant.grant_type == "invite_reward",
                QuotaGrant.created_at >= month_start,
            )
            .scalar()
        )
        if int(month_granted or 0) + reward <= monthly_cap:
            _grant_quota(db, inviter_user_id, "invite_reward", reward,
                         valid_days=valid_days, source_user_id=invited_user_id)

        # 里程碑自动到账（PRD 3.3）：累计邀请人数达档位且未领取，自动发放会员体验天数。
        milestones_cfg = _get_config_json(db, "invite_milestones") or []
        claimed = set(inviter_progress.claimed_targets or [])
        for m in milestones_cfg:
            tgt = int(m.get("invited") or 0)
            days = int(m.get("days") or 0)
            months = int(m.get("months") or 0)
            if tgt and (days > 0 or months > 0) and inviter_progress.invited_count >= tgt and tgt not in claimed:
                try:
                    _grant_subscription_days(db, inviter_user_id, days, months)
                    claimed.add(tgt)
                except Exception:
                    # 会员发放异常不应阻断邀请奖励主流程
                    pass
        inviter_progress.claimed_targets = sorted(claimed)
    return True


def _bind_device_or_fail(db: Session, user_id: str, device_id: str) -> None:
    binding = db.query(DeviceBinding).filter(DeviceBinding.device_id == device_id).first()
    if binding and binding.user_id != user_id:
        # 允许同一设备注册多个账号：已有绑定不覆盖、不阻断
        return
    if not binding:
        db.add(DeviceBinding(device_id=device_id, user_id=user_id))


def _ensure_commission_account(db: Session, user_id: str, for_update: bool = False) -> CommissionAccount:
    """获取（必要时创建）用户的返利账户，金额单位：分

    for_update=True 时对已存在行加 FOR UPDATE 行锁（P1 修复 2026-09-11），
    供提现申请等「读-改-写 pending_amount」路径使用，防止与下单/订单审批并发覆盖。
    """
    query = db.query(CommissionAccount).filter(CommissionAccount.user_id == user_id)
    if for_update:
        query = query.with_for_update()
    account = query.first()
    if not account:
        account = CommissionAccount(user_id=user_id, total_reward=0, withdrawn_amount=0, pending_amount=0)
        db.add(account)
        db.flush()
    return account


def _find_inviter_of(db: Session, user_id: str) -> Optional[str]:
    """查询某用户注册时使用的直接邀请人 user_id（无则返回 None）"""
    relation = db.query(InviteRelation).filter(InviteRelation.invited_user_id == user_id).first()
    return relation.inviter_user_id if relation else None


def _unlock_expired_commissions(db: Session, user_id: Optional[str] = None) -> None:
    """把已过解冻期的冻结佣金转为可提现（惰性解冻，读取汇总/明细前调用）。"""
    now = datetime.utcnow()
    query = db.query(CommissionRecord).filter(
        CommissionRecord.status == "frozen",
        CommissionRecord.freeze_until.isnot(None),
        CommissionRecord.freeze_until <= now,
    )
    if user_id:
        query = query.filter(CommissionRecord.recipient_user_id == user_id)
    for record in query.all():
        record.status = "available"
        account = db.query(CommissionAccount).filter(CommissionAccount.user_id == record.recipient_user_id).first()
        if account:
            account.frozen_amount = max(0, int(account.frozen_amount or 0) - int(record.amount or 0))


def _commission_summary(db: Session, user_id: str) -> Dict[str, int]:
    """汇总返利账户：累计 / 已提现 / 提现中 / 冻结中 / 可提现（分）。

    可提现 = 累计 − 冻结中 − 已提现 − 提现中；金额以账户字段为准（与 CommissionRecord 同步维护）。
    """
    _unlock_expired_commissions(db, user_id)
    account = db.query(CommissionAccount).filter(CommissionAccount.user_id == user_id).first()
    total = int(account.total_reward or 0) if account else 0
    withdrawn = int(account.withdrawn_amount or 0) if account else 0
    pending = int(account.pending_amount or 0) if account else 0
    frozen = int(account.frozen_amount or 0) if account else 0
    return {
        "totalReward": total,
        "withdrawnAmount": withdrawn,
        "pendingAmount": pending,
        "frozenAmount": frozen,
        "availableAmount": max(0, total - frozen - withdrawn - pending),
    }


def _distribute_commission_on_subscription(db: Session, recharge_user_id: str, plan: str,
                                           order_type: str = "first", order_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """单级返佣：订阅订单审批通过后，仅向直接邀请人（一级）发放固定佣金。

    规则（system_configs 可实时调整）：
        - 活动总开关 invite_activity_enabled=0 或返佣开关 invite_commission_enabled=0 → 不返佣；
        - 仅直接邀请人拿佣（单级，无二级）；
        - commission_inviter_paid=1 时，邀请人须 paid_once=1（已付费）才有佣金资格；
        - 首单佣金 = commission_first_fen[plan]（按套餐固定）；
          续费（renewal）佣金 = 首单佣金 × commission_renewal_pct / 100；
        - 佣金进入 commission_records(status=frozen)，解冻期 commission_freeze_days 天后可提现。
    """
    if _get_config_int(db, "invite_activity_enabled") != 1:
        return []
    if _get_config_int(db, "invite_commission_enabled") != 1:
        return []

    inviter_user_id = _find_inviter_of(db, recharge_user_id)
    if not inviter_user_id:
        return []
    inviter = db.query(User).filter(User.user_id == inviter_user_id).first()
    if not inviter:
        return []
    if _get_config_int(db, "commission_inviter_paid") == 1 and not inviter.paid_once:
        return []  # 仅已付费邀请人有佣金资格

    first_fen = _get_config_json(db, "commission_first_fen") or {}
    base = int(first_fen.get(plan) or 0)
    if base <= 0:
        return []
    amount = base
    if order_type == "renewal":
        renewal_pct = _get_config_int(db, "commission_renewal_pct")
        amount = max(0, base * renewal_pct // 100)
    if amount <= 0:
        return []

    freeze_days = _get_config_int(db, "commission_freeze_days")
    account = _ensure_commission_account(db, inviter_user_id)
    account.total_reward = int(account.total_reward or 0) + amount
    if freeze_days > 0:
        account.frozen_amount = int(account.frozen_amount or 0) + amount
        status, freeze_until = "frozen", datetime.utcnow() + timedelta(days=freeze_days)
    else:
        status, freeze_until = "available", None
    db.add(
        CommissionRecord(
            source_user_id=recharge_user_id,
            recipient_user_id=inviter_user_id,
            inviter_user_id=inviter_user_id,
            level=1,
            order_id=order_id,
            amount=amount,
            plan=plan,
            order_type=order_type,
            status=status,
            freeze_until=freeze_until,
        )
    )
    return [{"recipient": inviter_user_id, "level": 1, "amount": amount, "status": status}]


def _build_quota_dict(db: Session, quota: UserQuota) -> Dict[str, Any]:
    """构建统一配额响应（已移除每日免费额度与按次付费额度：剩余总次数 = 赠送额度聚合值）

    展示前先惰性清理过期批次并重算聚合余额，保证赠送额度/剩余总次数不含已过期部分。
    调用方（登录/注册/GET /quota）均在主流程 commit 之后才构建响应，此处提交安全。
    """
    _purge_expired_grants(db, quota.user_id)
    _sync_extra_balance(db, quota.user_id)
    db.commit()
    free_balance = int(quota.extra_balance or 0)
    return {
        "dailyFreeUsed": 0,
        "dailyFreeLimit": 0,
        "freeBalance": free_balance,
        "extraBalance": free_balance,
        "remainingTotal": free_balance,
        "lastResetDate": quota.last_reset_date,
    }


def _build_milestones(db: Session, progress: InviteProgress) -> List[Dict[str, Any]]:
    """里程碑列表（配置项 invite_milestones 与当前用户领取进度合并）"""
    claimed = set(progress.claimed_targets or [])
    return [
        {
            "invited": int(item.get("invited") or 0),
            "days": int(item.get("days") or 0),
            "label": item.get("label") or f"累计邀请{item.get('invited')}人",
            "claimed": int(item.get("invited") or 0) in claimed,
        }
        for item in (_get_config_json(db, "invite_milestones") or [])
    ]


def _sum_monthly_invite_granted(db: Session, user_id: str) -> int:
    """本月（UTC 自然月）按 invite_reward 发放到本人的邀请所得额度合计。

    取 quota_grants 中 grant_type='invite_reward' 且 created_at 在本月内的 amount 之和，
    与前端「本月邀请所得额度」卡片对应；发放侧已按 invite_reward_monthly_cap 限流，
    故此处为实际已得（非剩余）。
    """
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = db.query(func.coalesce(func.sum(QuotaGrant.amount), 0)).filter(
        QuotaGrant.user_id == user_id,
        QuotaGrant.grant_type == "invite_reward",
        QuotaGrant.created_at >= month_start,
    ).scalar()
    return int(total or 0)


def _build_invite_info(db: Session, user: User, progress: InviteProgress) -> Dict[str, Any]:
    """构建邀请有礼信息（单级返佣 + 可配置规则 + 活动总控 + 里程碑）"""
    return {
        "inviteCode": user.invite_code,
        "invitedCount": int(progress.invited_count or 0),
        # 活动总控
        "activityEnabled": _activity_enabled(db),
        "commissionEnabled": _get_config_int(db, "invite_commission_enabled") == 1,
        # 赠送与邀请额度规则（C 端展示同源）
        "newUserGiftQuota": _get_config_int(db, "new_user_gift_quota"),
        "newUserGiftValidDays": _get_config_int(db, "new_user_gift_valid_days"),
        "invitedExtraQuota": _get_config_int(db, "invited_extra_quota"),
        "invitedExtraValidDays": _get_config_int(db, "invited_extra_valid_days"),
        "inviteRewardQuota": _get_config_int(db, "invite_reward_quota"),
        "inviteRewardValidDays": _get_config_int(db, "invite_reward_valid_days"),
        "inviteRewardMonthlyCap": _get_config_int(db, "invite_reward_monthly_cap"),
        # 返佣规则
        "singleLevel": True,
        "commissionFirstFen": _get_config_json(db, "commission_first_fen"),
        "commissionRenewalPct": _get_config_int(db, "commission_renewal_pct"),
        "commissionFreezeDays": _get_config_int(db, "commission_freeze_days"),
        # 提现规则
        "withdrawMinFen": _get_config_int(db, "withdraw_min_fen"),
        "withdrawMonthlyTimes": _get_config_int(db, "withdraw_monthly_times"),
        # 本月邀请所得额度：本月自然月内（UTC）按 invite_reward 发放到本人的赠送次数合计
        "monthlyGranted": _sum_monthly_invite_granted(db, user.user_id),
        # 里程碑
        "milestones": _build_milestones(db, progress),
    }


def _build_invite_tree(db: Session, root_user_id: str, max_depth: int = 3) -> Optional[Dict[str, Any]]:
    """构建以 root_user_id 为根的邀请关系树（下游被邀请人），最多展开 max_depth 层"""
    nodes: Dict[str, Dict[str, Any]] = {root_user_id: {"username": None, "children": []}}
    current_level = [root_user_id]
    depth = 0
    while current_level and depth < max_depth:
        relations = (
            db.query(InviteRelation)
            .filter(InviteRelation.inviter_user_id.in_(current_level))
            .all()
        )
        next_level: List[str] = []
        for relation in relations:
            child_id = relation.invited_user_id
            if child_id in nodes:
                continue
            nodes[child_id] = {"username": None, "children": []}
            nodes[relation.inviter_user_id]["children"].append(child_id)
            next_level.append(child_id)
        current_level = next_level
        depth += 1

    user_ids = list(nodes.keys())
    if user_ids:
        for user in db.query(User).filter(User.user_id.in_(user_ids)).all():
            nodes[user.user_id]["username"] = user.username

    def build_node(node_id: str) -> Dict[str, Any]:
        node = nodes[node_id]
        return {
            "userId": node_id,
            "username": node["username"],
            "children": [build_node(child_id) for child_id in node["children"]],
        }

    return build_node(root_user_id)


def _build_ancestor_chain(db: Session, user_id: str) -> List[Dict[str, str]]:
    """沿邀请链上溯，返回该用户的所有上级邀请者（从直接上级到最顶层）"""
    chain: List[Dict[str, str]] = []
    visited: set = set()
    current_id = user_id
    while current_id and current_id not in visited:
        visited.add(current_id)
        inviter_id = _find_inviter_of(db, current_id)
        if not inviter_id:
            break
        inviter = db.query(User).filter(User.user_id == inviter_id).first()
        chain.append(
            {
                "userId": inviter_id,
                "username": inviter.username if inviter else None,
            }
        )
        current_id = inviter_id
    return chain


def _get_current_user_or_401(
    credentials: HTTPAuthorizationCredentials,
    db: Session,
) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="未登录")
    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.post("/device/check-binding")
def check_device_binding(payload: CheckDeviceBindingRequest, db: Session = Depends(get_db)):
    device_id = _require_valid_device_id(payload.deviceId)
    binding = db.query(DeviceBinding).filter(DeviceBinding.device_id == device_id).first()
    return {
        "isBound": bool(binding),
        "boundUserId": binding.user_id if binding else None,
    }


@router.get("/welfare-policy")
def get_welfare_policy(db: Session = Depends(get_db)):
    """福利政策（C 端首页/注册页未登录展示同源）：注册赠送/邀请奖励等数值一律取自后台系统配置，实时生效"""
    return {
        "success": True,
        "activityEnabled": _activity_enabled(db),
        "newUserGiftQuota": _get_config_int(db, "new_user_gift_quota"),
        "newUserGiftValidDays": _get_config_int(db, "new_user_gift_valid_days"),
        "invitedExtraQuota": _get_config_int(db, "invited_extra_quota"),
        "invitedExtraValidDays": _get_config_int(db, "invited_extra_valid_days"),
        "inviteRewardQuota": _get_config_int(db, "invite_reward_quota"),
        "inviteRewardValidDays": _get_config_int(db, "invite_reward_valid_days"),
        "inviteRewardMonthlyCap": _get_config_int(db, "invite_reward_monthly_cap"),
    }


@router.post("/invite/validate")
def validate_invite(payload: ValidateInviteRequest, db: Session = Depends(get_db)):
    code = _normalize_invite_code(payload.inviteCode)
    if not code:
        return {"isValid": False, "isOfficial": False, "inviterUserId": None}
    if _is_official_code(db, code):
        return {"isValid": True, "isOfficial": True, "inviterUserId": None}
    inviter = db.query(User).filter(User.invite_code == code).first()
    return {
        "isValid": bool(inviter),
        "isOfficial": False,
        "inviterUserId": inviter.user_id if inviter else None,
    }


@router.post("/auth/register")
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    username = (payload.username or "").strip()
    password = payload.password or ""
    confirm = payload.passwordConfirm or ""
    invite_code = _validate_invite_code_format(db, payload.inviteCode)
    device_id = _require_valid_device_id(payload.deviceId)

    if not USERNAME_PATTERN.fullmatch(username):
        raise HTTPException(status_code=400, detail="用户名需为2-20位中文/字母/数字")
    if len(password) < 6 or len(password) > 20:
        raise HTTPException(status_code=400, detail="密码长度需为6-20位")
    if password != confirm:
        raise HTTPException(status_code=400, detail="两次输入的密码不一致")

    existing_user = db.query(User).filter(User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已存在")

    inviter = _find_inviter_by_code(db, invite_code)
    if _is_official_code(db, invite_code):
        _touch_official_code(db, invite_code)

    user = User(
        user_id=str(uuid4()),
        username=username,
        grade=payload.grade if getattr(payload, 'grade', None) else None,
        phone=None,
        password_hash=hash_password(password),
        created_at=datetime.utcnow(),
        daily_max_calls=3,
        daily_calls_count=0,
        last_call_date=datetime.utcnow(),
        invite_code=_generate_unique_invite_code(db),
        first_login_reward_granted=False,
        ip_address=_get_client_ip(request),
    )
    db.add(user)
    db.flush()

    _bind_device_or_fail(db, user.user_id, device_id)
    _ensure_invite_progress(db, user.user_id)
    gift_reward = _grant_new_user_gift(db, user)

    if inviter and inviter.user_id != user.user_id:
        # 用 savepoint 隔离邀请关系写入：并发竞态或设备/用户唯一键冲突时，
        # 仅回滚该部分（不影响已创建的用户），避免整笔 commit 触发 500 导致注册失败。
        try:
            with db.begin_nested():
                counted = _upsert_invite_relation(
                    db, inviter.user_id, user.user_id, device_id, invited_ip=user.ip_address or ""
                )
                if counted:
                    # 被邀请人额外赠送额度（受活动总控，默认 5 次 / 30 天）
                    _grant_invited_extra(db, user.user_id, inviter.user_id)
        except IntegrityError:
            # 重复设备/用户导致的唯一键冲突：视为已计入，跳过即可，注册主流程照常成功
            logger.warning("邀请关系写入冲突（疑似重复设备/用户），已跳过，不影响注册")

    db.commit()

    quota = _ensure_user_quota(db, user.user_id)
    progress = _ensure_invite_progress(db, user.user_id)

    # 建立单会话：签发携带 sid 的 token 并写入 current_session_id（与 auth.create_session_token 一致）。
    # 否则 token 无 sid、current_session_id 为 NULL，verify_session_token 会因 not session_id 返回 None
    # → 注册成功后 /api/auth/me 立即 401 → 前端提示「你的账号已在别处登录」，需再手动登录一次。
    token = create_session_token(user, db)
    return {
        "success": True,
        "token": token,
        "needBindDevice": False,
        "message": "注册成功",
        "firstLoginRewardGranted": True,
        "firstLoginReward": gift_reward,
        "user": {
            "userId": user.user_id,
            "username": user.username,
            "inviteCode": user.invite_code,
            "grade": user.grade,
        },
        "quota": _build_quota_dict(db, quota),
        "inviteInfo": _build_invite_info(db, user, progress),
    }


@router.post("/auth/login/password")
def login_password(payload: LoginPasswordRequest, request: Request = None, db: Session = Depends(get_db)):
    username = (payload.username or "").strip()
    password = payload.password or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="请输入用户名和密码")

    user = db.query(User).filter(User.username == username).first()
    if not user or not user.password_hash or user.password_hash != hash_password(password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if payload.deviceId:
        device_id = _require_valid_device_id(payload.deviceId)
        binding = db.query(DeviceBinding).filter(DeviceBinding.device_id == device_id).first()
        user_binding = db.query(DeviceBinding).filter(DeviceBinding.user_id == user.user_id).first()
        if not binding and not user_binding:
            db.add(DeviceBinding(device_id=device_id, user_id=user.user_id))

    # 记录本次登录的客户端 IP（每次登录都刷新，仅保留最近一次登录 IP）
    if request is not None:
        ip = _get_client_ip(request)
        if ip and ip != "unknown":
            user.ip_address = ip

    quota = _ensure_user_quota(db, user.user_id)
    progress = _ensure_invite_progress(db, user.user_id)
    db.commit()

    # 与注册保持一致：签发携带 sid 的 token 并写入 current_session_id，避免登录后 /me 因 token 无 sid 被 401
    token = create_session_token(user, db)
    return {
        "success": True,
        "token": token,
        "user": {
            "userId": user.user_id,
            "username": user.username,
            "inviteCode": user.invite_code,
            "grade": user.grade,
        },
        "quota": _build_quota_dict(db, quota),
        "inviteInfo": _build_invite_info(db, user, progress),
    }


@router.post("/auth/login/phone")
def login_phone(payload: LoginPhoneRequest, request: Request = None, db: Session = Depends(get_db)):
    phone = (payload.phone or "").strip()
    code = (payload.code or "").strip()
    device_id = _require_valid_device_id(payload.deviceId)

    if not phone or not code:
        raise HTTPException(status_code=400, detail="手机号或验证码不能为空")
    if not verify_verification_code(db, phone, code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    user = db.query(User).filter(User.phone == phone).first()
    created = False

    if not user:
        created = True
        invite_code = _normalize_invite_code(payload.inviteCode)
        if not invite_code:
            raise HTTPException(status_code=400, detail="请填写邀请码（注册必填）")
        inviter = _find_inviter_by_code(db, invite_code)
        if _is_official_code(db, invite_code):
            _touch_official_code(db, invite_code)

        username = f"user_{phone[-4:]}"
        index = 1
        while db.query(User).filter(User.username == username).first():
            username = f"user_{phone[-4:]}_{index}"
            index += 1

        user = User(
            user_id=str(uuid4()),
            username=username,
            phone=phone,
            password_hash=hash_password(secrets.token_hex(8)),
            created_at=datetime.utcnow(),
            daily_max_calls=3,
            daily_calls_count=0,
            last_call_date=datetime.utcnow(),
            invite_code=_generate_unique_invite_code(db),
            first_login_reward_granted=False,
            ip_address=_get_client_ip(request) if request is not None else None,
        )
        db.add(user)
        db.flush()

        _bind_device_or_fail(db, user.user_id, device_id)
        _ensure_invite_progress(db, user.user_id)
        gift_reward = _grant_new_user_gift(db, user)

        if inviter and inviter.user_id != user.user_id:
            counted = _upsert_invite_relation(
                db, inviter.user_id, user.user_id, device_id, invited_ip=user.ip_address or ""
            )
            if counted:
                # 被邀请人额外赠送额度（受活动总控，默认 5 次 / 30 天）
                _grant_invited_extra(db, user.user_id, inviter.user_id)
    else:
        binding = db.query(DeviceBinding).filter(DeviceBinding.device_id == device_id).first()
        user_binding = db.query(DeviceBinding).filter(DeviceBinding.user_id == user.user_id).first()
        if not binding and not user_binding:
            db.add(DeviceBinding(device_id=device_id, user_id=user.user_id))

    quota = _ensure_user_quota(db, user.user_id)
    progress = _ensure_invite_progress(db, user.user_id)

    # 记录本次登录的客户端 IP（每次登录都刷新，仅保留最近一次登录 IP）
    if request is not None:
        ip = _get_client_ip(request)
        if ip and ip != "unknown":
            user.ip_address = ip

    delete_verification_code(db, phone)
    db.commit()

    token = create_session_token(user, db)
    return {
        "success": True,
        "token": token,
        "created": created,
        "firstLoginRewardGranted": created,
        "firstLoginReward": gift_reward if created else 0,
        "user": {
            "userId": user.user_id,
            "username": user.username,
            "phone": user.phone,
            "inviteCode": user.invite_code,
        },
        "quota": _build_quota_dict(db, quota),
        "inviteInfo": _build_invite_info(db, user, progress),
    }


@router.get("/invite/info")
def get_invite_info(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    user = _get_current_user_or_401(credentials, db)
    if not user.invite_code:
        user.invite_code = _generate_unique_invite_code(db)
    progress = _ensure_invite_progress(db, user.user_id)
    db.commit()

    return _build_invite_info(db, user, progress)


@router.get("/commission/summary")
def get_commission_summary(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """用户返利汇总：累计返利 / 已提现 / 提现中 / 可提现（单位：分）"""
    user = _get_current_user_or_401(credentials, db)
    summary = _commission_summary(db, user.user_id)
    return {
        "success": True,
        **summary,
    }


@router.get("/commission/records")
def get_commission_records(
    page: int = 1,
    page_size: int = 20,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """用户返利来源明细：每笔返利的来源用户、套餐、首单/续费、冻结状态、金额、产生时间"""
    user = _get_current_user_or_401(credentials, db)
    _unlock_expired_commissions(db, user.user_id)
    page = max(1, page)
    page_size = max(1, min(int(page_size), 50))
    offset = (page - 1) * page_size

    base_query = db.query(CommissionRecord).filter(
        CommissionRecord.recipient_user_id == user.user_id
    )
    total = base_query.count()
    records = (
        base_query.order_by(CommissionRecord.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    # 批量补全来源用户 / 直接邀请者用户名与邀请码
    user_ids = {r.source_user_id for r in records} | {r.inviter_user_id for r in records}
    username_map = {}
    invite_code_map = {}
    if user_ids:
        for u in db.query(User).filter(User.user_id.in_(user_ids)).all():
            username_map[u.user_id] = u.username
            invite_code_map[u.user_id] = u.invite_code

    items = []
    for record in records:
        items.append(
            {
                "id": record.id,
                "sourceUserId": record.source_user_id,
                "sourceUsername": username_map.get(record.source_user_id),
                "sourceInviteCode": invite_code_map.get(record.source_user_id),
                "inviterUsername": username_map.get(record.inviter_user_id),
                "inviterInviteCode": invite_code_map.get(record.inviter_user_id),
                "level": record.level,
                "amount": int(record.amount or 0),
                "plan": record.plan,
                "orderType": record.order_type,
                "orderId": record.order_id,
                "status": record.status,
                "freezeUntil": (record.freeze_until.isoformat() + "Z") if record.freeze_until else None,
                "createdAt": (record.created_at.isoformat() + "Z") if record.created_at else None,
            }
        )

    return {
        "success": True,
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/commission/withdrawals")
def get_my_withdrawal_requests(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """用户本人的提现申请记录"""
    user = _get_current_user_or_401(credentials, db)
    requests = (
        db.query(WithdrawalRequest)
        .filter(WithdrawalRequest.user_id == user.user_id)
        .order_by(WithdrawalRequest.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "success": True,
        "items": [
            {
                "requestId": req.request_id,
                "amount": int(req.amount or 0),
                "status": req.status,
                "adminNote": req.admin_note,
                "createdAt": (req.created_at.isoformat() + "Z") if req.created_at else None,
                "processedAt": (req.processed_at.isoformat() + "Z") if req.processed_at else None,
            }
            for req in requests
        ],
    }


@router.post("/commission/withdraw")
def withdraw_commission(
    payload: WithdrawCommissionRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """提交返利提现申请（提交后转入"提现中"，需管理员审核）"""
    user = _get_current_user_or_401(credentials, db)
    amount = int(payload.amount or 0)
    min_fen = _get_config_int(db, "withdraw_min_fen")
    monthly_times = _get_config_int(db, "withdraw_monthly_times")
    if amount < min_fen:
        raise HTTPException(status_code=400, detail=f"最低提现金额为 {min_fen / 100:.2f} 元")
    if amount % 1 != 0:
        raise HTTPException(status_code=400, detail="提现金额须为整数分")

    summary = _commission_summary(db, user.user_id)
    if amount > summary["availableAmount"]:
        raise HTTPException(status_code=400, detail=f"可提现返利不足，当前可提现 {summary['availableAmount'] / 100:.2f} 元")

    # 每月提现次数上限（配置 withdraw_monthly_times，默认 2 次/月）
    if monthly_times > 0:
        month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_count = (
            db.query(func.count(WithdrawalRequest.request_id))
            .filter(WithdrawalRequest.user_id == user.user_id, WithdrawalRequest.created_at >= month_start)
            .scalar()
        )
        if int(month_count or 0) >= monthly_times:
            raise HTTPException(status_code=400, detail=f"本月提现次数已达上限（{monthly_times} 次）")

    # P1 修复（2026-09-11）：冻结提现金额前加行锁，防止与下单预留/订单审批并发覆盖
    account = _ensure_commission_account(db, user.user_id, for_update=True)
    account.pending_amount = int(account.pending_amount or 0) + amount
    db.add(
        WithdrawalRequest(
            request_id=str(uuid4()),
            user_id=user.user_id,
            amount=amount,
            status="pending",
        )
    )
    db.commit()

    return {
        "success": True,
        "message": "提现申请已提交，请等待管理员审核",
        **(_commission_summary(db, user.user_id)),
    }


@router.get("/invite/tree")
def get_invite_tree(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """我的邀请关系树（下游被邀请人，最多 3 层，仅展示；返佣只到一级）"""
    user = _get_current_user_or_401(credentials, db)
    tree = _build_invite_tree(db, user.user_id, max_depth=INVITE_TREE_MAX_DEPTH)
    return {"success": True, "tree": tree}


@router.get("/invite/ancestors")
def get_invite_ancestors(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """我的所有上级邀请者（链式追溯，从直接上级到最顶层）"""
    user = _get_current_user_or_401(credentials, db)
    ancestors = _build_ancestor_chain(db, user.user_id)
    return {"success": True, "ancestors": ancestors}


@router.get("/quota")
def get_quota(
    deviceId: Optional[str] = None,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    if credentials and credentials.credentials:
        user = _get_current_user_or_401(credentials, db)
        quota = _ensure_user_quota(db, user.user_id)
        db.commit()
        return {
            "isLoggedIn": True,
            "subscription": _get_user_subscription(db, user.user_id),
            **_build_quota_dict(db, quota),
        }

    if not deviceId:
        raise HTTPException(status_code=400, detail="未登录时必须提供deviceId")

    device_id = _require_valid_device_id(deviceId)
    quota = _ensure_device_quota(db, device_id)
    db.commit()
    return {
        "isLoggedIn": False,
        "dailyFreeUsed": 0,
        "dailyFreeLimit": 0,
        "extraBalance": 0,
        "remainingTotal": 0,
        "lastResetDate": quota.last_reset_date,
    }


@router.get("/quota/grants")
def get_quota_grants(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """赠送额度明细：按实际到期日分组（同日合并次数、不同日分行），供个人中心「详情」下拉展示。

    到期日已计入会员期冻结规则——会员期内获得的批次，有效期顺延至会员到期后重新起算。
    """
    user = _get_current_user_or_401(credentials, db)
    _purge_expired_grants(db, user.user_id)
    _sync_extra_balance(db, user.user_id)
    db.commit()
    sub_expire = _get_subscription_expire_utc(db, user.user_id)
    now = datetime.utcnow()
    groups: Dict[str, Dict[str, Any]] = {}
    for grant in db.query(QuotaGrant).filter(
        QuotaGrant.user_id == user.user_id,
        QuotaGrant.remaining > 0,
    ).all():
        expire = _effective_expire(grant, sub_expire)
        if expire is not None and expire < now:
            continue
        key = expire.strftime("%Y-%m-%d") if expire else "longterm"
        group = groups.setdefault(
            key, {"expireAt": expire.isoformat() if expire else None, "remaining": 0}
        )
        group["remaining"] += int(grant.remaining or 0)
    items = sorted(groups.values(), key=lambda g: (g["expireAt"] is None, g["expireAt"] or ""))
    return {
        "success": True,
        "total": sum(item["remaining"] for item in items),
        "groups": items,
        "subscription": _get_user_subscription(db, user.user_id),
    }


# ==================== 订阅制（存于 system_configs，无需数据库变更） ====================

PLAN_MONTHS = {"monthly": 1, "quarterly": 3, "halfyear": 6, "yearly": 12}


def _add_natural_months(dt: datetime, months: int) -> datetime:
    """按自然月推进：保留开通当日的日序号，目标月没有该日则顺延到月末。

    例：1-15 开月度 -> 2-15；1-31 开季度 -> 4-30；2-28 开年度 -> 次年 2-28（相对顺延的同一天）。
    仅推进 年月日，时分秒微秒保持原值。
    """
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _get_plan_duration_months(db: Session, plan: str) -> int:
    """订阅自然月数：月度=1、季度=3、半年=6、年度=12 固定，不随后台可配额度时长(天)而变。"""
    return PLAN_MONTHS.get(plan, 0)


def _get_user_subscriptions(db: Session) -> Dict[str, Dict[str, Any]]:
    """读取全部订阅（key=user_subscriptions，value=JSON：{user_id: {plan, expire_at}}）"""
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "user_subscriptions").first()
    if not row or not row.config_value:
        return {}
    try:
        data = json.loads(row.config_value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_expire_at(value) -> Optional[datetime]:
    """解析订阅/封禁到期时间，统一为带时区 datetime。

    历史数据可能不带时区（naive），直接与 astimezone() 比较会抛 TypeError 导致 500；
    这里将无时区值按服务器本地时区补全，保证比较安全。解析失败返回 None。
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt


def _now_local() -> datetime:
    """订阅域时间约定：服务器本地时区（带时区）。

    注意与额度域区分：quota_grants 全程使用 datetime.utcnow()（UTC naive），
    两者各自自洽、绝对时刻一致（+08:00 本地 = 前 8 小时 UTC），但不要跨域混用。
    """
    return datetime.now().astimezone()


def _get_user_subscription(db: Session, user_id: str) -> Optional[Dict[str, Any]]:
    """返回用户当前有效订阅（未过期），无则 None"""
    subs = _get_user_subscriptions(db)
    info = subs.get(user_id)
    if not info or not info.get("expire_at"):
        return None
    expire = _parse_expire_at(info["expire_at"])
    if expire is None or _now_local() >= expire:
        return None
    return info


def _is_user_subscribed(db: Session, user_id: str) -> bool:
    """用户当前是否有有效订阅"""
    return _get_user_subscription(db, user_id) is not None


def _is_user_banned(db: Session, user_id: str) -> bool:
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "user_bans").first()
    if not row or not row.config_value:
        return False
    try:
        bans = json.loads(row.config_value)
        until = bans.get(user_id) if isinstance(bans, dict) else None
    except Exception:
        return False
    if not until:
        return False
    if until == "permanent":
        return True
    expire = _parse_expire_at(until)
    if expire is None:
        return True  # 解析失败按永久封禁处理（与原逻辑一致）
    return _now_local() < expire


def _set_user_subscription(db: Session, user_id: str, plan: str) -> Dict[str, Any]:
    """开通/续费订阅（自然月/季/年）：未过期则从原到期日顺延一个周期，否则从当前时间开始"""
    months = _get_plan_duration_months(db, plan)
    if not months:
        raise ValueError(f"未知订阅套餐: {plan}")
    subs = _get_user_subscriptions(db)
    now = _now_local()
    start = now
    current = subs.get(user_id)
    if current and current.get("expire_at"):
        cur_expire = _parse_expire_at(current["expire_at"])
        if cur_expire and cur_expire > now:
            start = cur_expire
    expire_at = _add_natural_months(start, months)
    subs[user_id] = {"plan": plan, "expire_at": expire_at.isoformat()}
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "user_subscriptions").first()
    value = json.dumps(subs, ensure_ascii=False)
    if row:
        row.config_value = value
    else:
        db.add(SystemConfig(config_key="user_subscriptions", config_value=value, description="用户订阅（value: JSON）"))


def _grant_subscription_days(db: Session, user_id: str, days: int = 0, months: int = 0) -> Dict[str, Any]:
    """里程碑奖励：按天或按自然月赠送会员有效期（未过期则顺延）；已有套餐时保留原 plan，否则记为 trial。

    - 传 months>0 时按自然月推进（如 30 天体验 → months=1），否则按 days（7 天体验 → days=7）。
    - 到期顺延基准与套餐续费一致：未过期从原到期时刻顺延，时分秒保持原到期值。
    """
    if months > 0:
        duration = months
    else:
        duration = int(days or 0)
    if duration <= 0:
        raise ValueError("会员天数必须大于 0")
    subs = _get_user_subscriptions(db)
    now = _now_local()
    start = now
    plan_label = "trial"
    current = subs.get(user_id)
    if current and current.get("expire_at"):
        cur_expire = _parse_expire_at(current["expire_at"])
        if cur_expire and cur_expire > now:
            start = cur_expire
            plan_label = current.get("plan") or "trial"
    expire_at = _add_natural_months(start, duration) if months > 0 else start + timedelta(days=duration)
    subs[user_id] = {"plan": plan_label, "expire_at": expire_at.isoformat()}
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "user_subscriptions").first()
    value = json.dumps(subs, ensure_ascii=False)
    if row:
        row.config_value = value
    else:
        db.add(SystemConfig(config_key="user_subscriptions", config_value=value, description="用户订阅（value: JSON）"))
    return {"plan": plan_label, "expire_at": expire_at.isoformat()}


@router.get("/subscription")
def get_my_subscription(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """查询当前用户的有效订阅（无则返回 null）"""
    if not credentials or not credentials.credentials:
        return {"success": True, "subscription": None}
    user = _get_current_user_or_401(credentials, db)
    sub = _get_user_subscription(db, user.user_id)
    return {"success": True, "subscription": sub}


class ClaimMilestoneRequest(BaseModel):
    invited: int  # 要领取的里程碑累计邀请人数


@router.get("/invite/milestones")
def get_my_milestones(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """我的累计邀请里程碑：规则与领取进度（活动关闭时 claimed 恒为 False，且不可领）"""
    user = _get_current_user_or_401(credentials, db)
    progress = _ensure_invite_progress(db, user.user_id)
    return {
        "success": True,
        "invitedCount": int(progress.invited_count or 0),
        "activityEnabled": _activity_enabled(db),
        "milestones": _build_milestones(db, progress),
    }


@router.post("/invite/milestones/claim")
def claim_milestone(
    payload: ClaimMilestoneRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """领取累计邀请里程碑奖励（赠送会员体验天数）"""
    user = _get_current_user_or_401(credentials, db)
    if not _activity_enabled(db):
        raise HTTPException(status_code=400, detail="邀请返利活动未开启，暂无法领取里程碑奖励")

    progress = _ensure_invite_progress(db, user.user_id)
    invited_target = int(payload.invited or 0)
    if int(progress.invited_count or 0) < invited_target:
        raise HTTPException(status_code=400, detail="暂未达到该里程碑的累计邀请人数")

    milestones = _get_config_json(db, "invite_milestones") or []
    claimed = set(progress.claimed_targets or [])
    if invited_target in claimed:
        raise HTTPException(status_code=400, detail="该里程碑奖励已领取过")

    target = next((m for m in milestones if int(m.get("invited") or 0) == invited_target), None)
    if not target:
        raise HTTPException(status_code=400, detail="里程碑不存在")

    days = int(target.get("days") or 0)
    months = int(target.get("months") or 0)
    if days <= 0 and months <= 0:
        raise HTTPException(status_code=400, detail="里程碑配置无效（缺少有效天数/月数）")

    subscription = _grant_subscription_days(db, user.user_id, days, months)
    claimed.add(invited_target)
    progress.claimed_targets = sorted(claimed)
    db.commit()

    return {
        "success": True,
        "message": f"领取成功：{target.get('label') or '会员体验'}已到账",
        "subscription": subscription,
        "milestones": _build_milestones(db, progress),
    }


@router.post("/generation/consume")
def consume_generation(
    payload: ConsumeRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    if credentials and credentials.credentials:
        user = _get_current_user_or_401(credentials, db)
        if _is_user_banned(db, user.user_id):
            raise HTTPException(
                status_code=403,
                detail="账号已被封禁，暂时无法使用内容生成功能",
            )
        quota = _ensure_user_quota(db, user.user_id)

        # 订阅用户：有效期内无限次使用，不消耗次数
        subscription = _get_user_subscription(db, user.user_id)
        if subscription:
            return {
                "success": True,
                "isLoggedIn": True,
                "subscribed": True,
                "subscriptionPlan": subscription["plan"],
                "subscriptionExpireAt": subscription["expire_at"],
                "dailyFreeUsed": 0,
                "dailyFreeLimit": 0,
                "freeBalance": int(quota.extra_balance or 0),
                "extraBalance": int(quota.extra_balance or 0),
                "remainingTotal": int(quota.extra_balance or 0),
                "message": f"订阅有效期内（至 {subscription['expire_at'][:10]}），本次生成不消耗次数",
            }

        if int(quota.extra_balance or 0) < 1:
            raise HTTPException(status_code=400, detail="生成次数不足，请前往个人中心查看剩余额度或充值后重试")

        # 批次 FIFO 扣减：优先扣最早到期批次（含过期批次清理与聚合余额重算）
        consumed = _consume_one_quota(db, user.user_id)
        db.commit()

        new_balance = int(quota.extra_balance or 0)
        if not consumed:
            raise HTTPException(status_code=400, detail="生成次数不足，请前往个人中心查看剩余额度或充值后重试")

        return {
            "success": True,
            "isLoggedIn": True,
            "dailyFreeUsed": 0,
            "dailyFreeLimit": 0,
            "freeBalance": new_balance,
            "extraBalance": new_balance,
            "remainingTotal": new_balance,
            "message": f"本次生成消耗 1 次，当前剩余总次数：{new_balance}",
        }

    # 匿名设备：每日免费额度已移除，未登录无法使用任何额度
    raise HTTPException(status_code=400, detail="登录状态失效或未登录，无法使用账户额度，请重新登录后再试")


@router.post("/generation/request")
def create_generation_request(
    payload: GenerationRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="请输入任务需求")

    consume_result = consume_generation(
        payload=ConsumeRequest(deviceId=payload.deviceId),
        credentials=credentials,
        db=db,
    )

    return {
        "success": True,
        "requestId": str(uuid4()),
        "prompt": prompt,
        "quota": {
            "dailyFreeUsed": 0,
            "dailyFreeLimit": 0,
            "extraBalance": consume_result["extraBalance"],
            "remainingTotal": consume_result["remainingTotal"],
        },
        "message": consume_result["message"],
    }


@router.post("/search/questions")
def search_questions(payload: SearchQuestionRequest, db: Session = Depends(get_db)):
    query_text = (payload.query or "").strip()
    if not query_text:
        return {"items": []}

    limit = max(1, min(int(payload.limit or 10), 20))
    rows = (
        db.query(Teaching.task_id, Teaching.question)
        .filter(Teaching.question.isnot(None))
        .order_by(Teaching.generated_at.desc())
        .limit(500)
        .all()
    )

    aggregated: Dict[str, str] = {}
    for task_id, question in rows:
        question_text = str(question or "").strip()
        if question_text:
            aggregated[str(task_id)] = question_text

    for item in _load_storage_candidates(limit=300):
        task_id = item.get("taskId")
        question_text = str(item.get("question") or "").strip()
        if task_id and question_text and task_id not in aggregated:
            aggregated[task_id] = question_text

    scored_items: List[Dict[str, Any]] = []
    for task_id, question_text in aggregated.items():
        score = _score_question(query_text, question_text)
        if score <= 0:
            continue
        scored_items.append({"taskId": task_id, "question": question_text, "score": score})

    scored_items.sort(key=lambda row: (-float(row["score"]), -len(str(row["question"]))))
    return {
        "items": [
            {"taskId": item["taskId"], "question": item["question"]}
            for item in scored_items[:limit]
        ]
    }


@router.delete("/account")
def delete_account(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    user = _get_current_user_or_401(credentials, db)
    user_id = user.user_id

    affected_inviter_ids = {
        row[0]
        for row in db.query(InviteRelation.inviter_user_id)
        .filter(InviteRelation.invited_user_id == user_id)
        .all()
    }

    db.query(CommentLike).filter(CommentLike.user_id == user_id).delete(synchronize_session=False)
    db.query(TeachingLike).filter(TeachingLike.user_id == user_id).delete(synchronize_session=False)
    db.query(Favorite).filter(Favorite.user_id == user_id).delete(synchronize_session=False)
    db.query(UserViewHistory).filter(UserViewHistory.user_id == user_id).delete(synchronize_session=False)
    db.query(Comment).filter(Comment.user_id == user_id).delete(synchronize_session=False)
    db.query(AITeachingQA).filter(AITeachingQA.user_id == user_id).delete(synchronize_session=False)
    db.query(Topic).filter(Topic.user_id == user_id).delete(synchronize_session=False)
    db.query(CommissionRecord).filter(
        (CommissionRecord.recipient_user_id == user_id)
        | (CommissionRecord.source_user_id == user_id)
        | (CommissionRecord.inviter_user_id == user_id)
    ).delete(synchronize_session=False)
    db.query(WithdrawalRequest).filter(WithdrawalRequest.user_id == user_id).delete(synchronize_session=False)
    db.query(CommissionAccount).filter(CommissionAccount.user_id == user_id).delete(synchronize_session=False)
    db.query(InviteRelation).filter(
        (InviteRelation.inviter_user_id == user_id) | (InviteRelation.invited_user_id == user_id)
    ).delete(synchronize_session=False)
    db.query(InviteProgress).filter(InviteProgress.user_id == user_id).delete(synchronize_session=False)
    db.query(QuotaGrant).filter(
        (QuotaGrant.user_id == user_id) | (QuotaGrant.source_user_id == user_id)
    ).delete(synchronize_session=False)
    db.query(UserQuota).filter(UserQuota.user_id == user_id).delete(synchronize_session=False)
    db.query(DeviceBinding).filter(DeviceBinding.user_id == user_id).delete(synchronize_session=False)

    db.query(Teaching).filter(Teaching.user_id == user_id).update(
        {Teaching.user_id: None},
        synchronize_session=False,
    )

    for inviter_user_id in affected_inviter_ids:
        count = (
            db.query(InviteRelation)
            .filter(InviteRelation.inviter_user_id == inviter_user_id)
            .count()
        )
        progress = db.query(InviteProgress).filter(InviteProgress.user_id == inviter_user_id).first()
        if progress:
            progress.invited_count = int(count)

    masked_user = db.query(User).filter(User.user_id == user_id).first()
    if masked_user:
        old_phone = masked_user.phone
        if old_phone:
            db.query(VerificationCode).filter(VerificationCode.phone == old_phone).delete(synchronize_session=False)
        masked_user.username = f"deleted_{user_id[:8]}_{secrets.randbelow(10000):04d}"
        masked_user.phone = None
        masked_user.email = None
        masked_user.password_hash = hash_password(secrets.token_hex(16))
        masked_user.invite_code = None
        masked_user.signature = None
        masked_user.grade = None
        masked_user.daily_calls_count = 0
        masked_user.daily_max_calls = 0
        masked_user.first_login_reward_granted = False

    db.commit()
    return {
        "success": True,
        "message": "账号已注销并清除相关数据",
    }
