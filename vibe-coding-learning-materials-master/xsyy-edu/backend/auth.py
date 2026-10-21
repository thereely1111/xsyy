"""
用户认证模块
提供登录、注册、忘记密码等功能
使用数据库存储（MySQL + SQLAlchemy）
"""

import hashlib
import secrets
import jwt
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Optional, List, Dict
from uuid import uuid4
from config import is_admin
from pydantic import BaseModel,AfterValidator
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import and_
from dotenv import load_dotenv
from database import get_db, SessionLocal, User, VerificationCode, Favorite, Teaching, InviteRelation, InviteProgress, UserQuota, SystemConfig, OfficialInviteCode

OFFICIAL_INVITE_CODE = os.getenv("BETA_CODE", "XSYY2026")
INVITE_PATTERN = re.compile(r"^[A-Z]{4}\d{4}$")

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# JWT 配置
JWT_SECRET = os.getenv("JWT_SECRET", "7aa4fa600d0b028fc2a08543e21bff2ff9dedefb9b88b72abb34f5a3b73cc5e0")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 48  # 2天


def trim_non_empty(v: str) -> tuple[bool, str]:
    """
    返回 (是否合法, 去除空白后的字符串)
    """
    s = v.strip()
    if not s:
        return False, ""
    return True, s

# 数据模型
class UserRegisterPassword(BaseModel):
    """用户名密码注册"""
    username: str
    password: str
    password_confirm: str
    beta_code: str  # 邀请码


class UserRegisterPhone(BaseModel):
    """手机号验证码注册"""
    phone: str
    verification_code: str
    beta_code: Optional[str] = ""  # 邀请码（可选，用于建立邀请关系）

class UserLogin(BaseModel):
    username: str
    password: str

class UserLoginPhone(BaseModel):
    """手机号登录"""
    phone: str
    verification_code: str

class SendVerificationCode(BaseModel):
    """发送验证码"""
    phone: str

class ForgotPassword(BaseModel):
    phone: str

class ResetPassword(BaseModel):
    phone: str
    verification_code: str
    new_password: str

class BindPhone(BaseModel):
    """绑定手机号"""
    phone: str
    verification_code: str

class BindEmail(BaseModel):
    """绑定邮箱"""
    email: str
    verification_code: str

class UpdateProfile(BaseModel):
    """更新个人资料"""
    username: Optional[str] = None
    grade: Optional[str] = None
    signature: Optional[str] = None

class ChangePassword(BaseModel):
    """修改密码"""
    current_password: str
    new_password: str
    new_password_confirm: str

class FavoriteAction(BaseModel):
    """收藏操作"""
    task_id: str
    action: Optional[str] = None  # 可选，如果不提供则自动判断（已收藏则移除，未收藏则添加）


# 工具函数
def hash_password(password: str) -> str:
    """使用 SHA256 加密密码"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_token(user_id: str, session_id: Optional[str] = None) -> str:
    """生成 JWT token，sid 用于普通账号单端互斥。"""
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow()
    }
    if session_id:
        payload["sid"] = session_id
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_session_token(user: User, db: Session) -> str:
    """登录成功后创建会话 token：普通账号覆盖旧会话，管理员允许并行。"""
    session_id = str(uuid4())
    if not is_admin(user.username):
        user.current_session_id = session_id
        db.flush()
        db.commit()
    return generate_token(user.user_id, session_id)


def verify_session_token(token: str, db: Session) -> Optional[str]:
    """验证 JWT token，普通账号必须匹配当前有效 sid，管理员跳过互斥。"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        session_id = payload.get("sid")
        if not user_id:
            return None

        user = db.query(User).filter(User.user_id == user_id).first()
        if not user:
            return None

        if is_admin(user.username):
            return user_id

        if not session_id or user.current_session_id != session_id:
            return None
        return user_id
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def verify_token(token: str, db: Optional[Session] = None) -> Optional[str]:
    """验证 JWT token，并对普通账号执行当前会话校验。"""
    if db is not None:
        return verify_session_token(token, db)

    session = SessionLocal()
    try:
        return verify_session_token(token, session)
    finally:
        session.close()

def generate_reset_token() -> str:
    """生成密码重置 token"""
    return secrets.token_urlsafe(32)

def generate_verification_code() -> str:
    """生成6位数字验证码"""
    return str(secrets.randbelow(900000) + 100000)

def save_verification_code(db: Session, phone: str, code: str) -> None:
    """保存验证码（5分钟有效期）"""
    expiry = datetime.utcnow() + timedelta(minutes=5)
    
    # 删除旧的验证码（如果存在）
    db.query(VerificationCode).filter(VerificationCode.phone == phone).delete()
    
    # 创建新验证码
    verification_code = VerificationCode(
        phone=phone,
        code=code,
        expiry=expiry
    )
    db.add(verification_code)
    db.commit()

def verify_verification_code(db: Session, phone: str, code: str) -> bool:
    """验证验证码"""
    verification_code = db.query(VerificationCode).filter(
        VerificationCode.phone == phone
    ).first()
    
    if not verification_code:
        return False
    
    if verification_code.code != code:
        return False
    
    # 检查是否过期
    if datetime.utcnow() > verification_code.expiry:
        # 删除过期验证码
        db.delete(verification_code)
        db.commit()
        return False
    
    return True

def delete_verification_code(db: Session, phone: str) -> None:
    """删除验证码"""
    db.query(VerificationCode).filter(VerificationCode.phone == phone).delete()
    db.commit()


def _is_official_invite_code(db: Session, code: str) -> bool:
    """邀请码是否为「启用中」的官方邀请码（来自 official_invite_codes 表）。

    兼容迁移过渡期：官方码表尚未初始化（记录数为 0）时，沿用历史硬编码官方码。
    """
    official = db.query(OfficialInviteCode).filter(
        OfficialInviteCode.code == code, OfficialInviteCode.is_active == True
    ).first()
    if official:
        return True
    if db.query(OfficialInviteCode).count() == 0 and code == OFFICIAL_INVITE_CODE:
        return True
    return False


def _validate_invite_code(db: Session, invite_code: str) -> Optional[User]:
    """验证邀请码，返回邀请人用户对象（官方邀请码返回None）。

    官方邀请码须来自 official_invite_codes 表（启用中）；用户邀请码须命中 users.invite_code。
    不在两者中的任意字符串一律拒绝。
    """
    code = (invite_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="请填写邀请码")
    if _is_official_invite_code(db, code):
        return None
    if not INVITE_PATTERN.fullmatch(code):
        raise HTTPException(status_code=400, detail="邀请码格式错误，请输入4位大写字母+4位数字")
    inviter = db.query(User).filter(User.invite_code == code).first()
    if not inviter:
        raise HTTPException(status_code=400, detail="邀请码错误，请检查后重试")
    return inviter


def _generate_unique_invite_code(db: Session) -> str:
    """生成唯一的用户邀请码（4位大写字母+4位数字）"""
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    for _ in range(100):
        code = "".join(secrets.choice(letters) for _ in range(4)) + f"{secrets.randbelow(10000):04d}"
        exists = db.query(User).filter(User.invite_code == code).first()
        if not exists:
            return code
    raise HTTPException(status_code=500, detail="邀请码生成失败，请稍后重试")


def _ensure_invite_progress(db: Session, user_id: str) -> InviteProgress:
    """确保用户有邀请进度记录，不存在则创建"""
    progress = db.query(InviteProgress).filter(InviteProgress.user_id == user_id).first()
    if not progress:
        progress = InviteProgress(user_id=user_id, invited_count=0, claimed_targets=[])
        db.add(progress)
        db.flush()
    if not isinstance(progress.claimed_targets, list):
        progress.claimed_targets = []
    return progress


def _upsert_invite_relation(db: Session, inviter_user_id: str, invited_user_id: str) -> None:
    """记录邀请关系并更新邀请人进度"""
    existed = db.query(InviteRelation).filter(InviteRelation.invited_user_id == invited_user_id).first()
    if existed:
        return
    
    db.add(
        InviteRelation(
            inviter_user_id=inviter_user_id,
            invited_user_id=invited_user_id,
            invited_device_id=invited_user_id,
        )
    )
    inviter_progress = _ensure_invite_progress(db, inviter_user_id)
    inviter_progress.invited_count = int(inviter_progress.invited_count or 0) + 1

    inviter_quota = db.query(UserQuota).filter(UserQuota.user_id == inviter_user_id).first()
    if not inviter_quota:
        from datetime import date
        inviter_quota = UserQuota(
            user_id=inviter_user_id,
            daily_free_used=0,
            extra_balance=0,
            last_reset_date=date.today().isoformat(),
        )
        db.add(inviter_quota)
        db.flush()
    invite_reward = _get_config_int(db, "invite_reward_quota", 3)
    inviter_quota.extra_balance = int(inviter_quota.extra_balance or 0) + invite_reward


def _get_config_int(db: Session, key: str, default: int) -> int:
    row = db.query(SystemConfig).filter(SystemConfig.config_key == key).first()
    if row and row.config_value is not None and str(row.config_value).strip() != "":
        try:
            return int(row.config_value)
        except (TypeError, ValueError):
            return default
    return default


def _grant_first_login_reward_v1(db: Session, user: User) -> None:
    """v1 注册/登录路径的首次登录赠送（幂等，flag 为 False 时发放一次）"""
    from datetime import date

    quota = db.query(UserQuota).filter(UserQuota.user_id == user.user_id).first()
    if not quota:
        quota = UserQuota(
            user_id=user.user_id,
            daily_free_used=0,
            extra_balance=0,
            last_reset_date=date.today().isoformat(),
        )
        db.add(quota)
        db.flush()
    if not user.first_login_reward_granted:
        reward = _get_config_int(db, "new_user_gift_quota", 5)
        quota.extra_balance = int(quota.extra_balance or 0) + reward
        user.first_login_reward_granted = True


# 业务逻辑
def register_user_password(user_data: UserRegisterPassword, db: Session, ip_address: Optional[str] = None) -> Dict:
    """用户名密码注册"""
    # 验证邀请码并获取邀请人
    inviter = _validate_invite_code(db, user_data.beta_code)
        
    valid, clean_username = trim_non_empty(user_data.username)
    if not valid:
        raise HTTPException(status_code=400, detail="用户名不能仅包含空白字符")
    # 检查用户名是否已存在
    existing_user = db.query(User).filter(User.username == clean_username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    # 创建新用户
    from uuid import uuid4
    user_id = str(uuid4())
    new_user = User(
        user_id=user_id,
        username=user_data.username,
        phone=None,
        password_hash=hash_password(user_data.password),
        created_at=datetime.utcnow(),
        daily_max_calls=3,
        daily_calls_count=0,
        last_call_date=datetime.utcnow(),
        invite_code=_generate_unique_invite_code(db),
        first_login_reward_granted=False,
        ip_address=ip_address,
    )
    db.add(new_user)
    db.flush()

    # 记录邀请关系并更新邀请人进度
    if inviter and inviter.user_id != user_id:
        _upsert_invite_relation(db, inviter.user_id, user_id)

    # 确保新用户有邀请进度记录
    _ensure_invite_progress(db, user_id)
    _grant_first_login_reward_v1(db, new_user)

    db.commit()
    db.refresh(new_user)
    
    token = create_session_token(new_user, db)
    
    return {
        "success": True,
        "message": "注册成功",
        "token": token,
        "user": {
            "username": user_data.username,
            "invite_code": new_user.invite_code,
        }
    }

def register_user_phone(user_data: UserRegisterPhone, db: Session, ip_address: Optional[str] = None) -> Dict:
    """手机号验证码注册"""
    # 验证验证码
    if not verify_verification_code(db, user_data.phone, user_data.verification_code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    
    # 检查手机号是否已注册
    existing_user = db.query(User).filter(User.phone == user_data.phone).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="该手机号已被注册")
    
    # 验证邀请码并获取邀请人
    inviter = _validate_invite_code(db, user_data.beta_code)

    # 创建新用户（使用手机号作为用户名）
    from uuid import uuid4
    user_id = str(uuid4())
    username = f"user_{user_data.phone[-4:]}"  # 使用手机号后4位作为默认用户名

    # 确保用户名唯一
    counter = 1
    original_username = username
    while db.query(User).filter(User.username == username).first():
        username = f"{original_username}_{counter}"
        counter += 1
    
    new_user = User(
        user_id=user_id,
        username=username,
        phone=user_data.phone,
        password_hash=None,  # 手机号注册不需要密码
        created_at=datetime.utcnow(),
        daily_max_calls=3,
        daily_calls_count=0,
        last_call_date=datetime.utcnow(),
        invite_code=_generate_unique_invite_code(db),
        first_login_reward_granted=False,
        ip_address=ip_address,
    )
    db.add(new_user)
    db.flush()

    # 记录邀请关系并更新邀请人进度
    if inviter and inviter.user_id != user_id:
        _upsert_invite_relation(db, inviter.user_id, user_id)

    # 确保新用户有邀请进度记录
    _ensure_invite_progress(db, user_id)
    _grant_first_login_reward_v1(db, new_user)
    db.commit()
    db.refresh(new_user)
    
    # 删除已使用的验证码
    delete_verification_code(db, user_data.phone)
    
    token = create_session_token(new_user, db)
    
    return {
        "success": True,
        "message": "注册成功",
        "token": token,
        "user": {
            "username": username,
            "phone": user_data.phone
        }
    }

def send_verification_code(phone_data: SendVerificationCode, db: Session) -> Dict:
    """发送验证码（演示模式，直接返回验证码）"""
    code = generate_verification_code()
    save_verification_code(db, phone_data.phone, code)
    
    # 在实际应用中，这里应该调用短信服务发送验证码
    # 演示模式下直接返回验证码
    return {
        "success": True,
        "message": "验证码已发送（演示模式，直接返回）",
        "verification_code": code  # 生产环境不应该返回这个
    }

def login_user(login_data: UserLogin, db: Session, ip_address: Optional[str] = None) -> Dict:
    """用户登录（用户名密码）"""
    user = db.query(User).filter(User.username == login_data.username).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    # 检查是否有密码（手机号注册的用户没有密码）
    if not user.password_hash:
        raise HTTPException(status_code=401, detail="该账号使用手机号登录，请使用验证码登录")
    
    password_hash = hash_password(login_data.password)
    
    if user.password_hash != password_hash:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 记录本次登录的客户端 IP（每次登录都刷新，仅保留最近一次登录 IP）
    if ip_address:
        user.ip_address = ip_address

    # 补发首次登录赠送（幂等，已发放的账号不受影响）
    _grant_first_login_reward_v1(db, user)
    db.commit()

    token = create_session_token(user, db)
    
    return {
        "success": True,
        "message": "登录成功",
        "token": token,
        "user": {
            "username": user.username,
            "phone": user.phone
        }
    }

def login_user_phone(login_data: UserLoginPhone, db: Session, ip_address: Optional[str] = None) -> Dict:
    """手机号验证码登录"""
    # 验证验证码
    if not verify_verification_code(db, login_data.phone, login_data.verification_code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    
    # 查找手机号对应的用户
    user = db.query(User).filter(User.phone == login_data.phone).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="该手机号未注册")

    # 记录本次登录的客户端 IP（每次登录都刷新，仅保留最近一次登录 IP）
    if ip_address:
        user.ip_address = ip_address

    # 补发首次登录赠送（幂等，已发放的账号不受影响）
    _grant_first_login_reward_v1(db, user)
    db.commit()

    token = create_session_token(user, db)
    
    # 删除已使用的验证码
    delete_verification_code(db, login_data.phone)
    
    return {
        "success": True,
        "message": "登录成功",
        "token": token,
        "user": {
            "username": user.username,
            "phone": user.phone
        }
    }

def forgot_password_request(forgot_data: ForgotPassword, db: Session) -> Dict:
    """忘记密码 - 发送验证码"""
    # 查找用户（通过手机号）
    user = db.query(User).filter(User.phone == forgot_data.phone).first()
    
    if not user:
        # 为了安全，即使手机号不存在也返回成功消息
        return {
            "success": True,
            "message": "如果该手机号已注册，验证码已发送"
        }
    
    # 检查用户是否有密码（手机号注册的用户没有密码，不需要重置）
    if not user.password_hash:
        raise HTTPException(status_code=400, detail="该账号使用手机号登录，无需重置密码")
    
    # 生成验证码
    code = generate_verification_code()
    save_verification_code(db, forgot_data.phone, code)
    
    # 在实际应用中，这里应该发送短信
    # 演示模式下直接返回验证码
    return {
        "success": True,
        "message": "验证码已发送（演示模式，直接返回）",
        "verification_code": code  # 生产环境不应该返回这个
    }

def reset_password(reset_data: ResetPassword, db: Session) -> Dict:
    """重置密码"""
    # 验证验证码
    if not verify_verification_code(db, reset_data.phone, reset_data.verification_code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    
    # 查找用户
    user = db.query(User).filter(User.phone == reset_data.phone).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 更新密码
    user.password_hash = hash_password(reset_data.new_password)
    user.reset_token = None
    user.reset_token_expiry = None
    db.commit()
    
    # 删除已使用的验证码
    delete_verification_code(db, reset_data.phone)
    
    return {
        "success": True,
        "message": "密码重置成功"
    }

def check_and_increment_daily_calls(user_id: str, db: Session) -> tuple[bool, str, int, int]:
    """
    检查并增加用户的每日调用次数
    
    Returns:
        (is_allowed, message, current_count, max_calls)
        - is_allowed: 是否允许调用
        - message: 提示信息
        - current_count: 当前已调用次数
        - max_calls: 最大调用次数
    """
    from datetime import date
    
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return False, "用户不存在", 0, 0
    
    today = date.today()
    
    # 检查是否需要重置计数（新的一天）
    if user.last_call_date is None or user.last_call_date.date() < today:
        user.daily_calls_count = 0
        user.last_call_date = datetime.utcnow()
        db.commit()
    
    # 检查是否超过限制
    if user.daily_calls_count >= user.daily_max_calls:
        return False, f"今日调用次数已达上限（{user.daily_max_calls}次），请明天再试", user.daily_calls_count, user.daily_max_calls
    
    # 增加调用次数
    user.daily_calls_count += 1
    user.last_call_date = datetime.utcnow()
    db.commit()
    
    remaining = user.daily_max_calls - user.daily_calls_count
    return True, f"调用成功，今日剩余 {remaining} 次", user.daily_calls_count, user.daily_max_calls

def update_user_daily_max_calls(user_id: str, max_calls: int, db: Session) -> Dict:
    """更新用户的每日最大调用次数"""
    if max_calls < 0:
        raise HTTPException(status_code=400, detail="最大调用次数不能为负数")
    
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user.daily_max_calls = max_calls
    db.commit()
    
    return {
        "success": True,
        "message": f"每日最大调用次数已更新为 {max_calls} 次",
        "daily_max_calls": max_calls
    }

def get_user_by_token(token: str, db: Session) -> Dict:
    """根据 token 获取用户信息"""
    user_id = verify_session_token(token, db)
    
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的 token")
    
    user = db.query(User).filter(User.user_id == user_id).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    from datetime import date
    today = date.today()
    
    # 检查是否需要重置计数（新的一天）
    if user.last_call_date is None or user.last_call_date.date() < today:
        user.daily_calls_count = 0
        user.last_call_date = datetime.utcnow()
        db.commit()
    
    # 每日免费额度统一以 UserQuota 为准（v2 额度系统扣减时只更新 daily_free_used/extra_balance）
    user_quota = db.query(UserQuota).filter(UserQuota.user_id == user.user_id).first()
    if user_quota is None:
        user_quota = UserQuota(
            user_id=user.user_id,
            daily_free_used=0,
            extra_balance=0,
            last_reset_date=today.isoformat(),
        )
        db.add(user_quota)
        db.flush()

    if user_quota.last_reset_date != today.isoformat():
        user_quota.last_reset_date = today.isoformat()
        user_quota.daily_free_used = 0
        db.commit()

    # 展示前惰性清理过期批次并重算聚合余额，保证赠送额度/剩余总次数不含已过期部分
    from invite_quota_api import _purge_expired_grants, _sync_extra_balance
    _purge_expired_grants(db, user.user_id)
    _sync_extra_balance(db, user.user_id)
    db.commit()

    free_balance = int(user_quota.extra_balance or 0)  # 赠送额度（注册赠送/邀请奖励等，聚合值）
    extra_balance = free_balance  # 按次付费额度已下线：额外余额 = 赠送额度
    remaining_total = extra_balance  # 每日免费额度已移除：剩余总次数 = 赠送额度
    last_reset_date = user_quota.last_reset_date

    # 当前有效订阅（会员期内无限次使用），前端据此把额度显示为“无限”
    from invite_quota_api import _get_user_subscription  # 局部导入，避免循环依赖
    subscription = _get_user_subscription(db, user.user_id)

    # 成功邀请人数（首页多态公告「会员态」占位符 {invited_count} 使用）
    from database.models import InviteProgress
    _progress = db.query(InviteProgress).filter(InviteProgress.user_id == user.user_id).first()
    invited_count = int(_progress.invited_count or 0) if _progress else 0

    return {
        "success": True,
        "user": {
            "username": user.username,
            "phone": user.phone,
            "email": user.email,
            "grade": user.grade,
            "signature": user.signature,
            "created_at": (user.created_at.isoformat() + "Z") if user.created_at else None,
            "daily_max_calls": user.daily_max_calls,
            "daily_calls_count": user.daily_calls_count,
            "remaining_calls": max(0, user.daily_max_calls - user.daily_calls_count),
            "daily_free_used": 0,
            "daily_free_limit": 0,
            "free_balance": free_balance,
            "paid_balance": 0,  # 按次付费已下线，保留字段以兼容旧版前端
            "extra_balance": extra_balance,
            "remaining_total": remaining_total,
            "last_reset_date": last_reset_date,
            "subscription": subscription,
            "invited_count": invited_count,
        }
    }

def bind_phone(user_id: str, bind_data: BindPhone, db: Session) -> Dict:
    """绑定手机号"""
    # 验证验证码
    if not verify_verification_code(db, bind_data.phone, bind_data.verification_code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    
    # 检查手机号是否已被其他用户使用
    existing_user = db.query(User).filter(
        and_(User.phone == bind_data.phone, User.user_id != user_id)
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="该手机号已被其他用户绑定")
    
    # 找到当前用户并更新手机号
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user.phone = bind_data.phone
    db.commit()
    
    # 删除已使用的验证码
    delete_verification_code(db, bind_data.phone)
    
    return {
        "success": True,
        "message": "手机号绑定成功",
        "user": {
            "username": user.username,
            "phone": bind_data.phone
        }
    }

def bind_email(user_id: str, bind_data: BindEmail, db: Session) -> Dict:
    """绑定邮箱（使用手机号验证码验证）"""
    # 查找用户
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    if not user.phone:
        raise HTTPException(status_code=400, detail="请先绑定手机号")
    
    # 验证验证码（使用已绑定的手机号）
    if not verify_verification_code(db, user.phone, bind_data.verification_code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    
    # 检查邮箱是否已被其他用户使用
    existing_user = db.query(User).filter(
        and_(User.email == bind_data.email, User.user_id != user_id)
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="该邮箱已被其他用户绑定")
    
    # 更新邮箱
    user.email = bind_data.email
    try:
        db.commit()
        # 删除已使用的验证码
        delete_verification_code(db, user.phone)
        
        return {
            "success": True,
            "message": "邮箱绑定成功",
            "user": {
                "username": user.username,
                "email": bind_data.email
            }
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"绑定邮箱失败: {str(e)}")

def update_profile(user_id: str, profile_data: UpdateProfile, db: Session) -> Dict:
    """更新个人资料（用户名、年级、签名）"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 更新用户名
    if profile_data.username is not None:
        new_username = profile_data.username.strip()
        if not new_username:
            raise HTTPException(status_code=400, detail="用户名不能为空")
        
        # 检查用户名长度
        if len(new_username) < 2 or len(new_username) > 50:
            raise HTTPException(status_code=400, detail="用户名长度必须在2-50个字符之间")
        
        # 检查用户名是否与当前用户名相同
        if new_username == user.username:
            # 用户名未改变，不需要更新
            pass
        else:
            # 检查用户名是否已被其他用户使用
            existing_user = db.query(User).filter(
                and_(User.username == new_username, User.user_id != user_id)
            ).first()
            if existing_user:
                raise HTTPException(status_code=400, detail="该用户名已被使用，请选择其他用户名")
            
            user.username = new_username
    
    # 更新年级
    if profile_data.grade is not None:
        user.grade = profile_data.grade
    
    # 更新个性签名
    if profile_data.signature is not None:
        user.signature = profile_data.signature
    
    try:
        db.commit()
        return {
            "success": True,
            "message": "资料更新成功",
            "user": {
                "username": user.username,
                "grade": user.grade,
                "signature": user.signature
            }
        }
    except HTTPException:
        # 重新抛出 HTTPException（如用户名已存在）
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"更新资料失败: {str(e)}")

def change_password(user_id: str, password_data: ChangePassword, db: Session) -> Dict:
    """修改密码"""
    # 检查密码确认
    if password_data.new_password != password_data.new_password_confirm:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")
    
    # 找到当前用户
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 检查是否有密码（手机号注册的用户没有密码）
    if not user.password_hash:
        raise HTTPException(status_code=400, detail="该账号使用手机号登录，无法修改密码")
    
    # 验证当前密码
    if user.password_hash != hash_password(password_data.current_password):
        raise HTTPException(status_code=400, detail="当前密码错误")
    
    # 更新密码
    user.password_hash = hash_password(password_data.new_password)
    db.commit()
    
    return {
        "success": True,
        "message": "密码修改成功"
    }

def toggle_favorite(user_id: str, favorite_data: FavoriteAction, db: Session) -> Dict:
    """添加或移除收藏"""
    # 检查教学内容是否存在
    teaching = db.query(Teaching).filter(Teaching.task_id == favorite_data.task_id).first()
    if not teaching:
        raise HTTPException(status_code=404, detail="教学内容不存在")
    
    # 检查用户是否存在
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 查找是否已收藏
    favorite = db.query(Favorite).filter(
        and_(Favorite.user_id == user_id, Favorite.task_id == favorite_data.task_id)
    ).first()
    
    # 如果指定了 action，按指定操作；否则自动切换（toggle）
    if favorite_data.action:
        if favorite_data.action == "add":
            # 添加收藏
            if not favorite:
                new_favorite = Favorite(
                    user_id=user_id,
                    task_id=favorite_data.task_id,
                    created_at=datetime.utcnow()
                )
                db.add(new_favorite)
                db.commit()
                return {
                    "success": True,
                    "message": "收藏成功",
                    "is_favorite": True
                }
            else:
                return {
                    "success": True,
                    "message": "已收藏",
                    "is_favorite": True
                }
        elif favorite_data.action == "remove":
            # 移除收藏
            if favorite:
                db.delete(favorite)
                db.commit()
                return {
                    "success": True,
                    "message": "取消收藏成功",
                    "is_favorite": False
                }
            else:
                return {
                    "success": True,
                    "message": "未收藏",
                    "is_favorite": False
                }
        else:
            raise HTTPException(status_code=400, detail="无效的操作，action 必须是 'add' 或 'remove'")
    else:
        # 自动切换：如果已收藏则移除，如果未收藏则添加
        if favorite:
            # 移除收藏
            db.delete(favorite)
            db.commit()
            return {
                "success": True,
                "message": "取消收藏成功",
                "is_favorite": False
            }
        else:
            # 添加收藏
            new_favorite = Favorite(
                user_id=user_id,
                task_id=favorite_data.task_id,
                created_at=datetime.utcnow()
            )
            db.add(new_favorite)
            db.commit()
            return {
                "success": True,
                "message": "收藏成功",
                "is_favorite": True
            }

def get_user_favorites(user_id: str, db: Session) -> List[dict]:
    """获取用户的收藏列表，带收藏时间"""
    favorites = db.query(Favorite).filter(Favorite.user_id == user_id).order_by(Favorite.created_at.desc()).all()
    result = []
    for fav in favorites:
        result.append({
            "task_id": fav.task_id,
            "created_at": (fav.created_at.isoformat() + "Z") if fav.created_at else None
        })
    return result
