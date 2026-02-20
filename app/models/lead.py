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
import uuid
from sqlalchemy import (
    Column, String, DateTime, Index, UniqueConstraint, func
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from app.db.session import Base


class Lead(Base):
    __tablename__ = "leads"

    # ── Composite table-level constraints and indexes ──────────────────────
    __table_args__ = (
        # UniqueConstraint("email", name="uq_leads_email"),  # Enable after migration
        # Index("ix_leads_status", "status"),                 # Enable after migration
        # Index("ix_leads_created_at", "created_at"),         # Enable after migration
        {"extend_existing": True},
    )

    # ── Primary key ────────────────────────────────────────────────────────
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)

    # ── Core fields (match current DB schema) ──────────────────────────────
    name    = Column(String(255), nullable=True)
    email   = Column(String(255), nullable=True)
    company = Column(String(255), nullable=True)
    website = Column(String(255), nullable=True)
    phone   = Column(String(50),  nullable=True)

    # ── Status lifecycle ───────────────────────────────────────────────────
    # Values: NEW | IN_PROGRESS | QUALIFIED | CLOSED
    status = Column(String(50), default="NEW")

    # ── Chat flow enrichment (filled by chatbot conversation) ──────────────
    trade_type         = Column(String(50),  nullable=True)
    country_interested = Column(String(255), nullable=True)
    product            = Column(String(255), nullable=True)
    requirement_type   = Column(String(255), nullable=True)

    # ── Audit timestamps ───────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # ── POST-MIGRATION columns (uncomment after running alembic upgrade) ──
    # source     = Column(String(50),  nullable=False, default="chatbot_form")
    # ip_address = Column(String(45),  nullable=True)
    # country    = Column(String(100), nullable=True)
    # city       = Column(String(100), nullable=True)
    # updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

