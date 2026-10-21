from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import User, Application, Problem
from app.core.security import get_current_user, require_role
from app.schemas.common import DashboardStats
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/dashboard")
async def get_dashboard(
    current_user: dict = Depends(require_role("admin", "creator")),
    db: AsyncSession = Depends(get_db)
):
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar()
    total_applications = (await db.execute(select(func.count()).select_from(Application))).scalar()
    total_problems = (await db.execute(select(func.count()).select_from(Problem))).scalar()

    return {
        "code": 200,
        "data": {
            "total_users": total_users,
            "total_applications": total_applications,
            "total_problems": total_problems,
            "active_users_today": 0,
            "applications_this_week": [],
            "popular_tags": [
                {"name": "代数", "count": 120},
                {"name": "几何", "count": 85},
                {"name": "概率", "count": 45}
            ]
        }
    }


@router.get("/users")
async def list_all_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: str = None,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    query = select(User)

    if role:
        query = query.where(User.role == role)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()

    query = query.order_by(User.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    users = result.scalars().all()

    return {
        "code": 200,
        "data": {
            "items": [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "role": u.role.value,
                    "is_active": u.is_active,
                    "created_at": u.created_at
                }
                for u in users
            ],
            "total": total,
            "page": page,
            "page_size": page_size
        }
    }


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    role: str,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.role = role
    await db.commit()

    return {"code": 200, "message": "角色更新成功"}


@router.patch("/users/{user_id}/status")
async def toggle_user_status(
    user_id: int,
    is_active: bool,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.is_active = is_active
    await db.commit()

    return {"code": 200, "message": "状态更新成功"}


@router.get("/applications/pending")
async def list_pending_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    query = select(Application).where(
        Application.is_published == True,
        Application.is_audited == False
    )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()

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
                    "author_id": a.author_id,
                    "primary_tag": a.primary_tag,
                    "created_at": a.created_at
                }
                for a in applications
            ],
            "total": total,
            "page": page,
            "page_size": page_size
        }
    }


@router.post("/applications/{application_id}/audit")
async def audit_application(
    application_id: int,
    approved: bool,
    message: str = None,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    app.is_audited = approved
    app.audit_message = message

    await db.commit()

    return {
        "code": 200,
        "message": "审核完成"
    }


@router.get("/problems/pending")
async def list_pending_problems(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db)
):
    query = select(Problem).where(Problem.is_audited == 0)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()

    query = query.order_by(Problem.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    problems = result.scalars().all()

    return {
        "code": 200,
        "data": {
            "items": [
                {
                    "id": p.id,
                    "title": p.title,
                    "author_id": p.author_id,
                    "primary_tag": p.primary_tag,
                    "created_at": p.created_at
                }
                for p in problems
            ],
            "total": total,
            "page": page,
            "page_size": page_size
        }
    }
