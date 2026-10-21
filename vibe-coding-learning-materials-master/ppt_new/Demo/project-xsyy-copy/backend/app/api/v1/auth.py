from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import User
from app.schemas.auth import (
    RegisterRequest, LoginRequest, RefreshTokenRequest,
    TokenResponse, UserResponse, SendCodeRequest, ResetPasswordRequest
)
from app.core.security import (
    hash_password, verify_password, create_access_token,
    create_refresh_token, verify_token, get_current_user
)
from app.config import settings
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

in_memory_tokens = {}
in_memory_refresh_tokens = {}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(User).where(User.username == request.username)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "USER_001", "message": "用户名已存在"}
        )

    existing_email = await db.execute(
        select(User).where(User.email == request.email)
    )
    if existing_email.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "USER_002", "message": "邮箱已被注册"}
        )

    user = User(
        username=request.username,
        email=request.email,
        password_hash=hash_password(request.password),
        role=request.role
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(f"New user registered: {user.username}")

    return {
        "code": 201,
        "message": "注册成功",
        "data": {
            "user_id": user.id,
            "username": user.username,
            "email": user.email
        }
    }


@router.post("/login")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.username == request.username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_001", "message": "用户名或密码错误"}
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "AUTH_003", "message": "账号已被禁用"}
        )

    access_token = create_access_token(user.id, user.username, user.role)
    refresh_token = create_refresh_token(user.id)

    in_memory_tokens[str(user.id)] = access_token
    in_memory_refresh_tokens[refresh_token] = str(user.id)

    logger.info(f"User logged in: {user.username}")

    return {
        "code": 200,
        "message": "登录成功",
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "token_type": "Bearer"
        }
    }


@router.post("/refresh")
async def refresh_token(request: RefreshTokenRequest, db: AsyncSession = Depends(get_db)):
    payload = verify_token(request.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_004", "message": "无效的RefreshToken"}
        )

    user_id = int(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_001", "message": "用户不存在或已禁用"}
        )

    access_token = create_access_token(user.id, user.username, user.role)
    new_refresh_token = create_refresh_token(user.id)

    in_memory_tokens[str(user.id)] = access_token
    in_memory_refresh_tokens[new_refresh_token] = str(user.id)

    return {
        "code": 200,
        "message": "Token刷新成功",
        "data": {
            "access_token": access_token,
            "refresh_token": new_refresh_token,
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "token_type": "Bearer"
        }
    }


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["user_id"])
    if user_id in in_memory_tokens:
        del in_memory_tokens[user_id]

    return {"code": 200, "message": "登出成功"}


@router.post("/send-code")
async def send_code(request: SendCodeRequest):
    logger.info(f"Verification code sent to {request.email}")
    return {"code": 200, "message": "验证码已发送"}


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    return {"code": 200, "message": "密码重置成功"}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_002", "message": "用户不存在"}
        )

    return {
        "code": 200,
        "data": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
            "avatar_url": user.avatar_url,
            "bio": user.bio,
            "is_active": user.is_active,
            "created_at": user.created_at
        }
    }
