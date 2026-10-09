import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.database import Base

json_type = JSON().with_variant(JSONB, 'postgresql')
id_type = String(36).with_variant(UUID(as_uuid=False), 'postgresql')


def utcnow():
    return datetime.now(timezone.utc)


class NoveltyReport(Base):
    __tablename__ = 'novelty_reports'
    id: Mapped[str] = mapped_column(id_type, primary_key=True, default=lambda: str(uuid.uuid4()))
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(160))
    field: Mapped[str] = mapped_column(String(160), default='')
    input_data: Mapped[dict] = mapped_column(json_type)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    stage: Mapped[str] = mapped_column(String(40), default='queued')
    progress: Mapped[int] = mapped_column(default=0)
    saved: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    report: Mapped[dict | None] = mapped_column(json_type)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NoveltyUsage(Base):
    __tablename__ = 'novelty_usage'
    id: Mapped[str] = mapped_column(id_type, primary_key=True, default=lambda: str(uuid.uuid4()))
    day_utc: Mapped[str] = mapped_column(String(10), index=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    analysis_id: Mapped[str] = mapped_column(id_type, index=True)
    calls_reserved: Mapped[int] = mapped_column(Integer, default=8)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default='reserved')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NoveltyDailyBudget(Base):
    __tablename__ = 'novelty_daily_budget'
    day_utc: Mapped[str] = mapped_column(String(10), primary_key=True)
    calls_reserved: Mapped[int] = mapped_column(Integer, default=0)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)


class GroqDailyBudget(Base):
    __tablename__ = 'groq_daily_budget'
    day_utc: Mapped[str] = mapped_column(String(10), primary_key=True)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)


class SerpApiUserBudget(Base):
    __tablename__ = 'serpapi_user_budget'
    subject: Mapped[str] = mapped_column(String(72), primary_key=True)
    day_ist: Mapped[str] = mapped_column(String(10), primary_key=True)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)


class NoveltyWorkspace(Base):
    __tablename__ = 'novelty_workspaces'
    report_id: Mapped[str] = mapped_column(id_type, primary_key=True)
    owner_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    review_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    comments: Mapped[list] = mapped_column(json_type, default=list)
    watched: Mapped[bool] = mapped_column(Boolean, default=False)
    latest_report_id: Mapped[str | None] = mapped_column(id_type)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchState(Base):
    __tablename__ = 'research_states'
    report_id: Mapped[str] = mapped_column(id_type, ForeignKey('novelty_reports.id', ondelete='CASCADE'), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    records: Mapped[dict] = mapped_column(json_type, default=dict)
    history: Mapped[list] = mapped_column(json_type, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
