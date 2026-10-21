from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ApplicationGenerateRequest(BaseModel):
    problem_id: Optional[int] = None
    analyze_result: dict
    question_content: str
    options: Optional[dict] = {
        "include_animation": True,
        "include_exercises": True,
        "exercise_count": 3,
        "style": "traditional"
    }


class ApplicationUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    is_published: Optional[bool] = None


class ApplicationResponse(BaseModel):
    id: int
    task_id: str
    problem_id: Optional[int] = None
    author_id: int
    title: str
    description: Optional[str] = None
    html_content: Optional[str] = None
    html_path: Optional[str] = None
    primary_tag: str
    secondary_tags: List[str] = []
    difficulty: str
    view_count: int = 0
    like_count: int = 0
    favorite_count: int = 0
    comment_count: int = 0
    is_published: bool = False
    is_audited: bool = False
    status: str
    progress: int = 0
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApplicationListResponse(BaseModel):
    items: List[ApplicationResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: int
    result: Optional[dict] = None
    error_message: Optional[str] = None


class ApplicationGenerateResponse(BaseModel):
    task_id: str
    status: str
    application_id: Optional[int] = None
