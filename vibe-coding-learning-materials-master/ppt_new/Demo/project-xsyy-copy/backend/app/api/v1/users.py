from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import User, Favorite, Application, Like
from app.schemas.user import UserProfileUpdate, UserProfileResponse, PublicUserInfo
from app.core.security import get_current_user
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/profile")
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    problem_count_result = await db.execute(
        select(func.count()).select_from(Application).where(
            Application.author_id == user.id
        )
    )
    problem_count = problem_count_result.scalar()

    return {
        "code": 200,
        "data": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "role": user.role.value,
            "avatar_url": user.avatar_url,
            "bio": user.bio,
            "is_active": user.is_active,
            "created_at": user.created_at,
            "problem_count": problem_count,
            "application_count": problem_count
        }
    }


@router.patch("/profile")
async def update_profile(
    request: UserProfileUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if request.username is not None:
        user.username = request.username
    if request.email is not None:
        user.email = request.email
    if request.phone is not None:
        user.phone = request.phone
    if request.avatar_url is not None:
        user.avatar_url = request.avatar_url
    if request.bio is not None:
        user.bio = request.bio

    await db.commit()

    return {"code": 200, "message": "更新成功"}


@router.get("/favorites")
async def get_favorites(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Favorite, Application).join(
        Application, Favorite.application_id == Application.id
    ).where(Favorite.user_id == current_user["user_id"])

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    query = query.order_by(Favorite.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    favorites = result.all()

    return {
        "code": 200,
        "data": {
            "items": [
                {
                    "id": fav.Application.id,
                    "title": fav.Application.title,
                    "primary_tag": fav.Application.primary_tag,
                    "created_at": fav.Favorite.created_at
                }
                for fav in favorites
            ],
            "total": total,
            "page": page,
            "page_size": page_size
        }
    }


@router.post("/favorites/{application_id}")
async def add_favorite(
    application_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    app_result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = app_result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    existing = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user["user_id"],
            Favorite.application_id == application_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="已收藏")

    favorite = Favorite(
        user_id=current_user["user_id"],
        application_id=application_id
    )
    db.add(favorite)

    app.favorite_count += 1
    await db.commit()

    return {"code": 200, "message": "收藏成功"}


@router.delete("/favorites/{application_id}")
async def remove_favorite(
    application_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user["user_id"],
            Favorite.application_id == application_id
        )
    )
    favorite = result.scalar_one_or_none()

    if not favorite:
        raise HTTPException(status_code=404, detail="收藏不存在")

    await db.delete(favorite)

    app_result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = app_result.scalar_one_or_none()
    if app and app.favorite_count > 0:
        app.favorite_count -= 1

    await db.commit()

    return {"code": 200, "message": "取消收藏成功"}


@router.post("/likes/{application_id}")
async def add_like(
    application_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    app_result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = app_result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    existing = await db.execute(
        select(Like).where(
            Like.user_id == current_user["user_id"],
            Like.application_id == application_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="已点赞")

    like = Like(
        user_id=current_user["user_id"],
        application_id=application_id
    )
    db.add(like)

    app.like_count += 1
    await db.commit()

    return {"code": 200, "message": "点赞成功"}


@router.delete("/likes/{application_id}")
async def remove_like(
    application_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Like).where(
            Like.user_id == current_user["user_id"],
            Like.application_id == application_id
        )
    )
    like = result.scalar_one_or_none()

    if not like:
        raise HTTPException(status_code=404, detail="点赞不存在")

    await db.delete(like)

    app_result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = app_result.scalar_one_or_none()
    if app and app.like_count > 0:
        app.like_count -= 1

    await db.commit()

    return {"code": 200, "message": "取消点赞成功"}


@router.get("/works")
async def get_my_works(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    query = select(Application).where(Application.author_id == current_user["user_id"])

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    query = query.order_by(Application.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    applications = result.scalars().all()

    return {
        "code": 200,
        "data": {
            "items": [
                {
                    "id": a.id,
                    "title": a.title,
                    "primary_tag": a.primary_tag,
                    "difficulty": a.difficulty,
                    "is_published": a.is_published,
                    "view_count": a.view_count,
                    "like_count": a.like_count,
                    "created_at": a.created_at
                }
                for a in applications
            ],
            "total": total,
            "page": page,
            "page_size": page_size
        }
    }
