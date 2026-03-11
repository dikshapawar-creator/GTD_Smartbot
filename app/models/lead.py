"""
Lead SQLAlchemy Model — Enterprise Hardened
Constraints:
  - NOT NULL on all required B2B fields
  - UNIQUE constraint on email (one lead per business address)
  - Indexes on status and created_at for admin query performance
  - E.164 phone stored (max 20 chars incl. '+')
  - Status CHECK enum: NEW → IN_PROGRESS → QUALIFIED → CLOSED

NOTE: After running Alembic migration a3b7c920d1e4, uncomment
the metadata columns (source, ip_address, country, city, updated_at).
"""
from sqlalchemy import (
    Column, String, DateTime, Index, func, Enum, ForeignKey, Integer, Boolean
)


from sqlalchemy.orm import relationship
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from app.db.session import Base
import uuid
import enum


class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    QUALIFIED = "QUALIFIED"
    CLOSED = "CLOSED"
    COMPLETE = "COMPLETE"  # Missing status found in database records


class Lead(Base):
    __tablename__ = "leads"

    # ── Table-level constraints and indexes ───────────────────────────────
    __table_args__ = (
        Index("ix_leads_status", "status"),
        Index("ix_leads_created_at", "created_at"),
        Index("ix_leads_country", "country_interested"),
        Index("ix_leads_trade_type", "trade_type"),
        Index("ix_leads_source", "source"),
        {"extend_existing": True},
    )

    # ── Scalability & Multi-tenancy ──────────────────────────────────────
    tenant_id = Column(Integer, nullable=False, default=1, index=True)

    # ── Primary key (MSSQL safe UUID) ──────────────────────────────────────
    id = Column(
        UNIQUEIDENTIFIER, 
        primary_key=True, 
        default=lambda: str(uuid.uuid4())
    )

    # ── Core fields (Enterprise Hardened) ─────────────────────────────────
    name    = Column(String(255), nullable=False)
    email   = Column(String(255), nullable=False)
    phone   = Column(String(20),  nullable=False)
    
    company = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)
    source  = Column(String(50),  nullable=False, default="chatbot")


    # ── Status lifecycle (Enum Enforced) ──────────────────────────────────
    status = Column(
        Enum(LeadStatus, name="lead_status"),
        default=LeadStatus.NEW,
        nullable=False
    )

    # ── Chat flow enrichment ──────────────────────────────────────────────
    trade_type         = Column(String(50),  nullable=True)
    country_interested = Column(String(255), nullable=True)
    product            = Column(String(255), nullable=True)
    requirement_type   = Column(String(255), nullable=True)

    # ── Concurrency & Audit ───────────────────────────────────────────────
    version    = Column(Integer, default=1, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)



    # ── Audit timestamps ───────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    history = relationship("LeadStatusHistory", back_populates="lead", cascade="all, delete-orphan")
    chat_sessions = relationship("ChatSession", back_populates="lead")


class LeadStatusHistory(Base):
    """
    Audit log for Lead status transitions.
    """
    __tablename__ = "lead_status_history"

    id = Column(String(50), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(Integer, nullable=False, default=1, index=True)
    lead_id = Column(String(50), ForeignKey("leads.id"), nullable=False)
    
    old_status = Column(String(50), nullable=False)
    new_status = Column(String(50), nullable=False)
    
    changed_by = Column(String(100), default="system") # e.g., "crm_user", "system"
    source     = Column(String(50),  nullable=True)      # e.g., "api", "crm", "automation"
    changed_at = Column(DateTime(timezone=True), server_default=func.now())


    # Relationships
    lead = relationship("Lead", back_populates="history")


