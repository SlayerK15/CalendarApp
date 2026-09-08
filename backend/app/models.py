from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None).replace(microsecond=0)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200))
    tokens: Mapped[str] = mapped_column(Text)


class AuthFlow(Base):
    __tablename__ = "auth_flows"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    binding: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ticket: Mapped[str | None] = mapped_column(String(64), unique=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class Session(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(200))
    sheet_gid: Mapped[str] = mapped_column(String(40))
    programme: Mapped[str] = mapped_column(String(200), default="")
    section: Mapped[str] = mapped_column(String(100), default="")
    calendar_id: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    event_count: Mapped[int] = mapped_column(Integer, default=0)


class Watch(Base):
    __tablename__ = "watches"
    channel_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(300))
    expiration: Mapped[datetime] = mapped_column(DateTime)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("source_id", "row_id"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    row_id: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSON)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    status: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
