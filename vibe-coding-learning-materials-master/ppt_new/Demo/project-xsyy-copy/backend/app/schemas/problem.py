from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ProblemCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    content: str
    image_url: Optional[str] = None


class ProblemUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    content: Optional[str] = None


class ProblemResponse(BaseModel):
    id: int
    author_id: int
    title: str
    description: Optional[str] = None
    content: str
    cleaned_content: Optional[str] = None
    image_url: Optional[str] = None
    primary_tag: str
    secondary_tags: List[str] = []
    difficulty: str
    knowledge_points: List[dict] = []
    view_count: int = 0
    like_count: int = 0
    favorite_count: int = 0
    is_audited: int = 0
    audit_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ProblemListResponse(BaseModel):
    items: List[ProblemResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ProblemAnalyzeRequest(BaseModel):
    content: str
    image_url: Optional[str] = None
    image_base64: Optional[str] = None


class ProblemAnalyzeResult(BaseModel):
    title: str
    primary_tag: str
    secondary_tags: List[str]
    difficulty: str
    knowledge_points: List[dict]
    estimated_time: int


class ProblemValidationResponse(BaseModel):
    is_math: bool
    confidence: float
    has_graph: bool
    reason: str
