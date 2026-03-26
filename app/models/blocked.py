from sqlalchemy import Column, String, DateTime, Index, Integer, ForeignKey
from app.db.session import Base
from datetime import datetime
import uuid

class BlockedVisitor(Base):
    """
    Registry for blocked visitors to prevent spam and abuse.
    Blocks are enforced by IP address and/or visitor fingerprint.
    """
    __tablename__ = "blocked_visitors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    
    ip_address = Column(String(45), nullable=True, index=True)
    visitor_fingerprint = Column(String(12), nullable=True, index=True)
    
    reason = Column(String(255), nullable=True)
    blocked_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_blocked_tenant_ip", "tenant_id", "ip_address"),
        Index("ix_blocked_tenant_fp", "tenant_id", "visitor_fingerprint"),
    )
