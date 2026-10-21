from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class CommentCreate(BaseModel):
    application_id: int
    content: str = Field(..., min_length=1, max_length=1000)
    parent_id: Optional[int] = None


class CommentResponse(BaseModel):
    id: int
    user_id: int
    application_id: int
    parent_id: Optional[int] = None
    content: str
    is_deleted: bool
    created_at: datetime
    user: Optional[dict] = None
    reply_count: int = 0

    class Config:
        from_attributes = True


class CommentListResponse(BaseModel):
    items: List[CommentResponse]
    total: int
    page: int
    page_size: int
