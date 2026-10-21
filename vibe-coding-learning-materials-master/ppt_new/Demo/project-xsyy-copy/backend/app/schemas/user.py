from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserProfileUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    avatar_url: Optional[str] = None
    bio: Optional[str] = Field(None, max_length=500)


class UserProfileResponse(BaseModel):
    id: int
    username: str
    email: EmailStr
    phone: Optional[str] = None
    role: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    is_active: bool
    created_at: datetime
    problem_count: int = 0
    application_count: int = 0

    class Config:
        from_attributes = True


class PublicUserInfo(BaseModel):
    id: int
    username: str
    avatar_url: Optional[str] = None
    role: str

    class Config:
        from_attributes = True
