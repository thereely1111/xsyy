from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import User, Problem
from app.schemas.problem import (
    ProblemCreate, ProblemUpdate, ProblemResponse,
    ProblemListResponse, ProblemAnalyzeRequest, ProblemAnalyzeResult,
    ProblemValidationResponse
)
from app.core.security import get_current_user
from app.services.ai_service import ai_service
from app.services.problem_service import problem_service, ProblemValidationError
import uuid
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

task_store = {}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_problem(
    request: ProblemCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        problem = await problem_service["create"](
            content=request.content,
            title=request.title,
            description=request.description,
            image_url=request.image_url,
            db=db,
            author_id=current_user["user_id"]
        )
        return {
            "code": 201,
            "message": "题目创建成功",
            "data": {
                "id": problem.id,
                "title": problem.title
            }
        }
    except ProblemValidationError as e:
        logger.warning(f"Problem validation failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": e.code, "message": e.message}
        )


@router.get("")
async def list_problems(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tag: str = None,
    difficulty: str = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(Problem).where(Problem.is_audited == 1)

    if tag:
        query = query.where(Problem.primary_tag == tag)
    if difficulty:
        query = query.where(Problem.difficulty == difficulty)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    query = query.order_by(Problem.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    problems = result.scalars().all()

    return {
        "code": 200,
        "message": "success",
        "data": {
            "items": [
                {
                    "id": p.id,
                    "title": p.title,
                    "primary_tag": p.primary_tag,
                    "difficulty": p.difficulty,
                    "view_count": p.view_count,
                    "created_at": p.created_at
                }
                for p in problems
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size
        }
    }


@router.get("/{problem_id}")
async def get_problem(
    problem_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Problem).where(Problem.id == problem_id))
    problem = result.scalar_one_or_none()

    if not problem:
        raise HTTPException(status_code=404, detail="题目不存在")

    problem.view_count += 1
    await db.commit()

    return {
        "code": 200,
        "data": {
            "id": problem.id,
            "title": problem.title,
            "description": problem.description,
            "content": problem.content,
            "primary_tag": problem.primary_tag,
            "secondary_tags": problem.secondary_tags or [],
            "difficulty": problem.difficulty,
            "knowledge_points": problem.knowledge_points or [],
            "view_count": problem.view_count,
            "created_at": problem.created_at
        }
    }


@router.post("/validate", response_model=ProblemValidationResponse)
async def validate_problem(
    request: ProblemAnalyzeRequest,
    current_user: dict = Depends(get_current_user)
):
    try:
        validation_result = await problem_service["validate"](
            content=request.content,
            image_base64=request.image_base64,
            author_id=current_user["user_id"]
        )
        return validation_result
    except ProblemValidationError as e:
        logger.warning(f"Problem validation failed: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": e.code, "message": e.message}
        )


@router.post("/analyze")
async def analyze_problem(
    request: ProblemAnalyzeRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    task_id = f"task_{uuid.uuid4().hex[:12]}"

    task_store[task_id] = {
        "status": "pending",
        "progress": 0,
        "result": None,
        "error": None
    }

    background_tasks.add_task(run_analysis, task_id, request.content)

    return {
        "code": 202,
        "message": "分析任务已提交",
        "data": {
            "task_id": task_id,
            "status": "pending"
        }
    }


async def run_analysis(task_id: str, content: str):
    try:
        task_store[task_id]["status"] = "processing"
        task_store[task_id]["progress"] = 5

        try:
            validation = await problem_service["validate"](content=content)
            task_store[task_id]["progress"] = 10
        except ProblemValidationError as e:
            task_store[task_id]["status"] = "failed"
            task_store[task_id]["error"] = {"code": e.code, "message": e.message}
            return

        result = await ai_service.analyze_problem(content)

        task_store[task_id]["progress"] = 90
        task_store[task_id]["status"] = "success"
        task_store[task_id]["result"] = result
        task_store[task_id]["progress"] = 100

    except Exception as e:
        task_store[task_id]["status"] = "failed"
        task_store[task_id]["error"] = str(e)
        logger.error(f"Analysis failed for {task_id}: {e}")


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in task_store:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = task_store[task_id]
    return {
        "code": 200,
        "data": {
            "task_id": task_id,
            "status": task["status"],
            "progress": task["progress"],
            "result": task.get("result"),
            "error_message": task.get("error")
        }
    }
