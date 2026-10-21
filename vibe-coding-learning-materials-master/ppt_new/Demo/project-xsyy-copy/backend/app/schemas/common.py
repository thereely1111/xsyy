from pydantic import BaseModel
from typing import List, Optional


class SimilarApplication(BaseModel):
    id: int
    title: str
    primary_tag: str
    difficulty: str
    similarity: float
    author: dict


class RecommendResponse(BaseModel):
    items: List[SimilarApplication]


class PopularApplication(BaseModel):
    id: int
    title: str
    primary_tag: str
    difficulty: str
    view_count: int
    author: dict


class PopularResponse(BaseModel):
    items: List[PopularApplication]


class DashboardStats(BaseModel):
    total_users: int
    total_applications: int
    total_problems: int
    active_users_today: int
    applications_this_week: List[dict]
    popular_tags: List[dict]
