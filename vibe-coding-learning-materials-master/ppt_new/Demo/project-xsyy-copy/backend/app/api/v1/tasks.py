from fastapi import APIRouter, HTTPException
from app.api.v1.problems import task_store as problem_tasks
from app.api.v1.applications import task_store as application_tasks
from app.models import Application
from app.database import AsyncSessionLocal
from sqlalchemy import select
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{task_id}")
async def get_task_status(task_id: str):
    if task_id in problem_tasks:
        task = problem_tasks[task_id]
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

    if task_id in application_tasks:
        task = application_tasks[task_id]
        return {
            "code": 200,
            "data": {
                "task_id": task_id,
                "status": task["status"],
                "progress": task["progress"],
                "application_id": task.get("application_id"),
                "result": task.get("result"),
                "error_message": task.get("error")
            }
        }

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Application).where(Application.task_id == task_id)
        )
        app = result.scalar_one_or_none()

        if app:
            return {
                "code": 200,
                "data": {
                    "task_id": task_id,
                    "status": app.status,
                    "progress": app.progress,
                    "application_id": app.id,
                    "error_message": app.error_message
                }
            }

    raise HTTPException(status_code=404, detail="任务不存在")
