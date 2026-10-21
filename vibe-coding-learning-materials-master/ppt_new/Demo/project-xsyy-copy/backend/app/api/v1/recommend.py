from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import Application
from app.services.vector_service import get_vector_service
from app.core.security import get_current_user_optional
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/similar")
async def recommend_similar(
    app_id: int = None,
    text: str = None,
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db)
):
    if not app_id and not text:
        return {
            "code": 400,
            "message": "需要提供app_id或text参数"
        }

    if app_id:
        result = await db.execute(
            select(Application).where(Application.id == app_id)
        )
        app = result.scalar_one_or_none()
        if app:
            text = app.title + " " + (app.description or "")

    vector_service = get_vector_service()

    if vector_service and text:
        try:
            embedding = await vector_service.get_embedding(text)
            similar = vector_service.search_similar(embedding, limit)

            if similar and similar.get("ids"):
                app_ids = [int(id) for id in similar["ids"][0]]
                scores = similar.get("distances", [[]])[0]

                apps_result = await db.execute(
                    select(Application).where(Application.id.in_(app_ids))
                )
                apps = apps_result.scalars().all()

                apps_dict = {a.id: a for a in apps}

                items = []
                for i, app_id in enumerate(app_ids):
                    app = apps_dict.get(app_id)
                    if app:
                        items.append({
                            "id": app.id,
                            "title": app.title,
                            "primary_tag": app.primary_tag,
                            "difficulty": app.difficulty,
                            "similarity": 1 - scores[i] if i < len(scores) else 0,
                            "author": {
                                "id": 0,
                                "username": "unknown"
                            }
                        })

                return {
                    "code": 200,
                    "data": {"items": items}
                }
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")

    query = select(Application).where(
        Application.is_published == True,
        Application.is_audited == True
    ).order_by(Application.view_count.desc()).limit(limit)

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
                    "similarity": 1.0,
                    "author": {"id": 0, "username": "unknown"}
                }
                for a in applications
            ]
        }
    }


@router.get("/popular")
async def recommend_popular(
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db)
):
    query = select(Application).where(
        Application.is_published == True,
        Application.is_audited == True
    ).order_by(Application.view_count.desc()).limit(limit)

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
                    "view_count": a.view_count,
                    "author": {"id": 0, "username": "unknown"}
                }
                for a in applications
            ]
        }
    }


@router.get("/latest")
async def recommend_latest(
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db)
):
    query = select(Application).where(
        Application.is_published == True,
        Application.is_audited == True
    ).order_by(Application.created_at.desc()).limit(limit)

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
                    "created_at": a.created_at,
                    "author": {"id": 0, "username": "unknown"}
                }
                for a in applications
            ]
        }
    }
