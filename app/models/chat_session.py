"""
ChatSession model — SQL Server source of truth for all chat sessions.
Includes enterprise features: inactivity tracking, metrics, optimized indexing,
and human agent takeover state management.
"""
import uuid
from sqlalchemy import (
    Column, String, DateTime, Boolean, BigInteger, Integer, Index, ForeignKey
)
from app.db.session import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # Server-generated UUID v4, carried as HTTP-only cookie by browser
    session_id = Column(String(36), nullable=False, unique=True, index=True)

    # Optional — if the platform adds auth later
    user_id = Column(String(255), nullable=True)

    # IP & Geolocation — captured ONCE at session creation
    ip_address = Column(String(45), nullable=True)
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    timezone = Column(String(100), nullable=True, default="UTC")

    # Lifecycle & Activity Tracking
    started_at_utc = Column(DateTime, nullable=False, index=True)
    started_at_local = Column(DateTime, nullable=False)
    last_activity_utc = Column(DateTime, nullable=False, index=True)
    ended_at_utc = Column(DateTime, nullable=True)
    ended_at_local = Column(DateTime, nullable=True)

    # Metrics
    total_messages = Column(Integer, default=0, nullable=False)
    duration_seconds = Column(Integer, nullable=True)

    # Session state flag
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Greeting tracking (Loop prevention)
    has_greeted = Column(Boolean, default=False, nullable=False)

    # Chatbot conversation state stored in DB (replaces in-memory dict)
    chat_state = Column(String(50), nullable=False, default="TRADE_TYPE")

    # ── Human Agent Takeover ──────────────────────────────────────────────
    # State machine: bot → waiting_for_agent → human → closed
    status = Column(String(20), nullable=False, default="bot", index=True)
    # FK to users.id — the agent currently handling this conversation
    assigned_agent_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Prevents multiple agents from claiming the same conversation
    is_locked = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_chat_sessions_session_id_active", "session_id", "is_active"),
        Index("ix_chat_sessions_last_activity", "last_activity_utc"),
        Index("ix_chat_sessions_status", "status"),
    )
