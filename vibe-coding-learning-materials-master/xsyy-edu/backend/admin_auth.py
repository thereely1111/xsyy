"""
管理员认证模块
提供管理员权限验证功能
"""

import time

from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

from auth import verify_token, get_user_by_token
from database import get_db, User
from config import is_admin

# HTTP Bearer Token 安全方案
security = HTTPBearer(auto_error=False)

# 用户鉴权短缓存（2026-09-01）：verify_token 后查 users 表每请求 1 次往返，
# 缓存 30s 缓解并发压力。对象经 db.expunge 分离后可跨请求安全复用。
# 注意：用户被删/封禁等变更最多延迟 30s 生效（可接受）。
_USER_CACHE_TTL = 30.0
_user_cache: dict = {}  # user_id -> (expire_ts, user)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    从 JWT token 中获取当前用户
    
    Args:
        credentials: HTTP Bearer token 凭证
        db: 数据库会话
        
    Returns:
        当前用户对象
        
    Raises:
        HTTPException: token 无效或用户不存在
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="未提供认证令牌"
        )
    token = credentials.credentials
    user_id = verify_token(token)
    
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="无效的认证令牌"
        )

    # 命中短缓存直接返回（expunge 分离后的对象，字段完整可用）
    _now = time.time()
    _cached = _user_cache.get(user_id)
    if _cached and _cached[0] > _now:
        return _cached[1]

    # 直接从数据库查询 User 对象，而不是使用 get_user_by_token（它返回字典）
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=401,
            detail="用户不存在或已被删除"
        )
    try:
        db.expunge(user)  # 从 session 分离，允许跨请求安全复用
    except Exception:
        pass
    _user_cache[user_id] = (_now + _USER_CACHE_TTL, user)
    return user


async def require_admin(
    user: User = Depends(get_current_user)
) -> User:
    """
    验证当前用户是否为管理员
    用于保护需要管理员权限的接口
    
    Args:
        user: 当前用户对象（从 get_current_user 依赖注入）
        
    Returns:
        管理员用户对象
        
    Raises:
        HTTPException: 用户不是管理员
    """
    if not is_admin(user.username):
        raise HTTPException(
            status_code=403,
            detail="需要管理员权限"
        )
    
    return user

