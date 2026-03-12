"""
ChatSession model — SQL Server source of truth for all chat sessions.
Includes enterprise features: inactivity tracking, metrics, optimized indexing,
and human agent takeover state management.
"""
import uuid
from sqlalchemy import (
    Column, String, DateTime, Boolean, BigInteger, Integer, Index, ForeignKey, Enum
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from app.db.session import Base
import enum


class SessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ConversationMode(str, enum.Enum):
    BOT = "BOT"
    HUMAN = "HUMAN"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    # Scalability & Multi-tenancy
    tenant_id = Column(Integer, nullable=False, default=1, index=True)

    # Server-generated UUID v4
    session_id = Column(String(36), nullable=False, unique=True, index=True)
    session_uuid = Column(UNIQUEIDENTIFIER, nullable=False, unique=True, index=True, default=uuid.uuid4)

    # Ownership & Linkage
    user_id = Column(String(255), nullable=True)
    lead_id = Column(UNIQUEIDENTIFIER, ForeignKey("leads.id"), nullable=True, index=True)

    # Relationships
    lead = relationship("Lead", back_populates="chat_sessions")

    # IP & Identity Tracking
    initial_ip = Column(String(45), nullable=True) # Static per session
    last_seen_ip = Column(String(45), nullable=True) # Tracks mobile rotation
    last_seen_at = Column(DateTime, nullable=True)
    visitor_fingerprint = Column(String(12), nullable=True, index=True) # Device identity
    visitor_uuid = Column(String(36), nullable=False, index=True) # Persistent browser identity
    
    # Geolocation
    country = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    timezone = Column(String(100), nullable=True, default="UTC")

    # Client Metadata
    user_agent = Column(String(500), nullable=True)
    browser = Column(String(100), nullable=True)
    os = Column(String(100), nullable=True)
    device_type = Column(String(50), nullable=True)

    # Lifecycle State
    session_status = Column(
        Enum(SessionStatus, name="session_status_enum"), 
        nullable=False, 
        default=SessionStatus.ACTIVE, 
        index=True
    )
    
    # Handler State
    conversation_mode = Column(
        Enum(ConversationMode, name="conversation_mode_enum"), 
        nullable=False, 
        default=ConversationMode.BOT, 
        index=True
    )

    # Lifecycle Timestamps
    started_at_utc = Column(DateTime, nullable=False, index=True)
    started_at_local = Column(DateTime, nullable=False)
    last_activity_utc = Column(DateTime, nullable=False, index=True)
    ended_at_utc = Column(DateTime, nullable=True)
    ended_at_local = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    
    # Agent Assignment
    assigned_agent_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    assigned_at = Column(DateTime, nullable=True)

    # Concurrency & Soft Delete
    version = Column(Integer, default=1, nullable=False) # Optimistic Locking
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)  # DB has this as NOT NULL BIT

    # Metrics & UI Helpers
    total_messages = Column(Integer, default=0, nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    is_locked = Column(Boolean, default=False, nullable=False)
    agent_joined = Column(Boolean, default=False, nullable=False) # Bot uses this to stop replying
    has_greeted = Column(Boolean, default=False, nullable=False)
    chat_state = Column(String(50), nullable=False, default="START")
    
    # Analytics & Scoring Extensions
    lead_score = Column(Integer, nullable=False, default=0)
    lead_status = Column(String(50), nullable=False, default="Cold")
    spam_flag = Column(Boolean, nullable=False, default=False)
    language = Column(String(50), nullable=True, default="en")

    # Legacy field (kept for migration compatibility) — non-nullable in some DB versions
    status = Column(String(50), nullable=False, default="ACTIVE")

    __table_args__ = (
        # ── Primary query: live dashboard — tenant's active sessions by recency
        Index("ix_sessions_tenant_status_activity", "tenant_id", "session_status", "last_activity_utc"),
        # ── History page: all tenant sessions ordered by time (covers date filters)
        Index("ix_sessions_tenant_activity_desc", "tenant_id", "last_activity_utc"),
        # ── Soft-delete guard — frequently paired with all filters
        Index("ix_sessions_tenant_deleted", "tenant_id", "is_deleted"),
        # ── Repeat visitor aggregation: lead history lookup by tenant
        Index("ix_sessions_tenant_lead", "tenant_id", "lead_id"),
        # Fingerprint lookup for analytics
        Index("ix_sessions_tenant_fingerprint", "tenant_id", "visitor_fingerprint"),
        # ── Mode filter for intervention dashboard
        Index("ix_sessions_active_mode", "session_status", "conversation_mode", "is_deleted"),
        # ── Agent workload queries
        Index("ix_sessions_agent", "assigned_agent_id", "session_status"),
    )

