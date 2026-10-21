from sqlalchemy import Column, BigInteger, ForeignKey, DateTime, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    application_id = Column(BigInteger, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)

    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="favorites")
    application = relationship("Application", back_populates="favorites")

    __table_args__ = (
        UniqueConstraint("user_id", "application_id", name="uk_user_app"),
        Index("idx_user", "user_id"),
        Index("idx_application", "application_id"),
    )
