from sqlalchemy import Column, BigInteger, String, Text, Enum, Integer, ForeignKey, DateTime, JSON, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class Difficulty(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"
    olympiad = "olympiad"


class Problem(Base):
    __tablename__ = "problems"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    author_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    cleaned_content = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)

    primary_tag = Column(String(50), nullable=False, index=True)
    secondary_tags = Column(JSON, default=list)
    difficulty = Column(Enum(Difficulty), default=Difficulty.medium)
    knowledge_points = Column(JSON, default=list)

    view_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)
    favorite_count = Column(Integer, default=0)

    is_audited = Column(Integer, default=0)
    audit_message = Column(String(500), nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    author = relationship("User", back_populates="problems")
    applications = relationship("Application", back_populates="problem", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_author", "author_id"),
        Index("idx_difficulty", "difficulty"),
    )
