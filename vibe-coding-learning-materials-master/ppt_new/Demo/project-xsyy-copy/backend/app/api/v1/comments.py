from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import Comment, Application
from app.schemas.comment import CommentCreate, CommentResponse, CommentListResponse
from app.core.security import get_current_user
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("")
async def create_comment(
    request: CommentCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    app_result = await db.execute(
        select(Application).where(Application.id == request.application_id)
    )
    app = app_result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    comment = Comment(
        user_id=current_user["user_id"],
        application_id=request.application_id,
        content=request.content,
        parent_id=request.parent_id
    )
    db.add(comment)

    app.comment_count += 1
    await db.commit()
    await db.refresh(comment)

    return {
        "code": 201,
        "message": "评论成功",
        "data": {
            "id": comment.id,
            "content": comment.content,
            "created_at": comment.created_at
        }
    }


@router.get("/application/{application_id}")
async def list_comments(
    application_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    query = select(Comment).where(
        Comment.application_id == application_id,
        Comment.is_deleted == False
    )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    query = query.order_by(Comment.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    comments = result.scalars().all()

    return {
        "code": 200,
        "data": {
            "items": [
                {
                    "id": c.id,
                    "user_id": c.user_id,
                    "application_id": c.application_id,
                    "content": c.content,
                    "parent_id": c.parent_id,
                    "created_at": c.created_at,
                    "reply_count": 0
                }
                for c in comments
            ],
            "total": total,
            "page": page,
            "page_size": page_size
        }
    }


@router.delete("/{comment_id}")
async def delete_comment(
    comment_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one_or_none()

    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在")

    if comment.user_id != current_user["user_id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="无权删除此评论")

    comment.is_deleted = True
    await db.commit()

    return {"code": 200, "message": "删除成功"}
