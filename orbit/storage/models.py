"""SQLAlchemy models owned by the ORBIT AI core.

Only durable, cross-cutting state belongs here. Domain tables (conversations,
agents, memory, tasks) are added in their respective milestones through new
Alembic revisions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    """Declarative base shared by every ORBIT AI model."""


class SystemState(Base):
    """Small key/value table for first-run state and schema bookkeeping."""

    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
