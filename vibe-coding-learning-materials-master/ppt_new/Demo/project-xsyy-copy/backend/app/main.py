from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os
import logging

from app.config import settings
from app.api.v1 import auth, problems, applications, comments, users, admin, recommend, tasks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    os.makedirs(settings.GENERATED_APPS_DIR, exist_ok=True)
    os.makedirs(settings.CHROMA_PATH, exist_ok=True)
    logger.info(f"XSYY Application started: {settings.APP_NAME} v{settings.APP_VERSION}")
    yield
    logger.info("XSYY Application shutdown")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI驱动的数学教学应用生成平台",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": "SYSTEM_001",
            "message": "系统内部错误",
            "detail": str(exc) if settings.DEBUG else None
        }
    )


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(problems.router, prefix="/api/v1/problems", tags=["题目"])
app.include_router(applications.router, prefix="/api/v1/applications", tags=["应用"])
app.include_router(comments.router, prefix="/api/v1/comments", tags=["评论"])
app.include_router(users.router, prefix="/api/v1/users", tags=["用户"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["管理后台"])
app.include_router(recommend.router, prefix="/api/v1/recommend", tags=["推荐"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["任务"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
