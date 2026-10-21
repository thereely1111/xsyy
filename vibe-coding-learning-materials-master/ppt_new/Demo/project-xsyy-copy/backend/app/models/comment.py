from sqlalchemy import Column, BigInteger, Text, ForeignKey, DateTime, Boolean, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Comment(Base):
    __tablename__ = "comments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    application_id = Column(BigInteger, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(BigInteger, ForeignKey("comments.id", ondelete="SET NULL"), nullable=True)

    content = Column(Text, nullable=False)
    is_deleted = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="comments")
    application = relationship("Application", back_populates="comments")
    parent = relationship("Comment", remote_side=[id], backref="replies")

    __table_args__ = (
        Index("idx_application", "application_id"),
        Index("idx_user", "user_id"),
    )
