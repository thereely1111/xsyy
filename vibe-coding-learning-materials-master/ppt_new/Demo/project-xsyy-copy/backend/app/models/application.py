from sqlalchemy import Column, BigInteger, String, Text, Integer, ForeignKey, DateTime, Boolean, Enum, JSON, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class TaskStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    success = "success"
    failed = "failed"


class Application(Base):
    __tablename__ = "applications"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String(100), unique=True, nullable=False, index=True)

    problem_id = Column(BigInteger, ForeignKey("problems.id", ondelete="SET NULL"), nullable=True)
    author_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    html_content = Column(Text, nullable=True)
    html_path = Column(String(500), nullable=True)

    primary_tag = Column(String(50), nullable=False)
    secondary_tags = Column(JSON, default=list)
    difficulty = Column(String(20), default="medium")

    view_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)
    favorite_count = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)

    is_published = Column(Boolean, default=False)
    is_audited = Column(Boolean, default=False)
    audit_message = Column(String(500), nullable=True)

    status = Column(Enum(TaskStatus), default=TaskStatus.pending)
    progress = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime, nullable=True)

    author = relationship("User", back_populates="applications")
    problem = relationship("Problem", back_populates="applications")
    comments = relationship("Comment", back_populates="application", cascade="all, delete-orphan")
    likes = relationship("Like", back_populates="application", cascade="all, delete-orphan")
    favorites = relationship("Favorite", back_populates="application", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_author", "author_id"),
        Index("idx_problem", "problem_id"),
        Index("idx_status", "status"),
        Index("idx_published", "is_published", "is_audited"),
    )
