from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import Application, Problem
from app.schemas.application import (
    ApplicationGenerateRequest, ApplicationUpdate, ApplicationResponse,
    ApplicationListResponse, TaskStatusResponse, ApplicationGenerateResponse
)
from app.core.security import get_current_user
from app.services.ai_service import ai_service
from app.config import settings
import uuid
import os
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

task_store = {}


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_application(
    request: ApplicationGenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    application = Application(
        task_id=task_id,
        author_id=current_user["user_id"],
        title=request.analyze_result.get("title", "未命名应用"),
        primary_tag=request.analyze_result.get("primary_tag", "数学"),
        secondary_tags=request.analyze_result.get("secondary_tags", []),
        difficulty=request.analyze_result.get("difficulty", "medium"),
        status="pending",
        progress=0
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)

    task_store[task_id] = {
        "status": "pending",
        "progress": 0,
        "application_id": application.id,
        "result": None,
        "error": None
    }

    background_tasks.add_task(
        run_generation, task_id, application.id,
        request.analyze_result, request.question_content, request.options
    )

    return {
        "code": 202,
        "message": "生成任务已提交",
        "data": {
            "task_id": task_id,
            "status": "pending",
            "application_id": application.id
        }
    }


async def run_generation(
    task_id: str,
    application_id: int,
    analyze_result: dict,
    question_content: str,
    options: dict
):
    from app.database import AsyncSessionLocal

    try:
        task_store[task_id]["status"] = "processing"
        update_application_status(application_id, "processing", 5)

        teaching_steps = await ai_service.generate_teaching_steps(
            question_content, analyze_result
        )
        task_store[task_id]["progress"] = 30
        update_application_status(application_id, "processing", 30)

        html_content = await ai_service.generate_application(
            analyze_result, question_content, options, teaching_steps
        )

        update_application_status(application_id, "processing", 70)

        html_path = os.path.join(settings.GENERATED_APPS_DIR, f"{application_id}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Application).where(Application.id == application_id)
            )
            app = result.scalar_one_or_none()
            if app:
                app.html_content = html_content
                app.html_path = html_path
                app.status = "success"
                app.progress = 100
                await db.commit()

        task_store[task_id]["status"] = "success"
        task_store[task_id]["progress"] = 100
        task_store[task_id]["result"] = {"html_path": html_path}

    except Exception as e:
        logger.error(f"Generation failed for {task_id}: {e}")
        task_store[task_id]["status"] = "failed"
        task_store[task_id]["error"] = str(e)
        update_application_status(application_id, "failed", 0, str(e))


def update_application_status(application_id: int, status: str, progress: int, error: str = None):
    import asyncio
    from app.database import AsyncSessionLocal

    async def _update():
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Application).where(Application.id == application_id)
            )
            app = result.scalar_one_or_none()
            if app:
                app.status = status
                app.progress = progress
                if error:
                    app.error_message = error
                await db.commit()

    asyncio.create_task(_update())


@router.get("")
async def list_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tag: str = None,
    difficulty: str = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(Application).where(
        Application.is_published == True,
        Application.is_audited == True
    )

    if tag:
        query = query.where(Application.primary_tag == tag)
    if difficulty:
        query = query.where(Application.difficulty == difficulty)

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
                    "view_count": a.view_count,
                    "like_count": a.like_count,
                    "created_at": a.created_at
                }
                for a in applications
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size
        }
    }


@router.get("/{application_id}")
async def get_application(
    application_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    app.view_count += 1
    await db.commit()

    return {
        "code": 200,
        "data": {
            "id": app.id,
            "title": app.title,
            "description": app.description,
            "html_content": app.html_content,
            "primary_tag": app.primary_tag,
            "secondary_tags": app.secondary_tags or [],
            "difficulty": app.difficulty,
            "view_count": app.view_count,
            "like_count": app.like_count,
            "favorite_count": app.favorite_count,
            "comment_count": app.comment_count,
            "is_published": app.is_published,
            "status": app.status,
            "created_at": app.created_at
        }
    }


@router.get("/{application_id}/status")
async def get_application_status(
    application_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    return {
        "code": 200,
        "data": {
            "task_id": app.task_id,
            "status": app.status,
            "progress": app.progress,
            "error_message": app.error_message
        }
    }


@router.get("/{application_id}/download")
async def download_application(
    application_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()

    if not app or not app.html_path:
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        app.html_path,
        media_type="text/html",
        filename=f"{app.title}.html"
    )


@router.patch("/{application_id}")
async def update_application(
    application_id: int,
    request: ApplicationUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    if app.author_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="无权修改此应用")

    if request.title is not None:
        app.title = request.title
    if request.description is not None:
        app.description = request.description
    if request.is_published is not None:
        app.is_published = request.is_published

    await db.commit()

    return {"code": 200, "message": "更新成功"}


@router.delete("/{application_id}")
async def delete_application(
    application_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Application).where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()

    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")

    if app.author_id != current_user["user_id"] and current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="无权删除此应用")

    await db.delete(app)
    await db.commit()

    return {"code": 200, "message": "删除成功"}
