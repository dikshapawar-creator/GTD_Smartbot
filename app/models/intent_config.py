"""
IntentConfig model — Stores dynamic intent keywords and response templates.
Allows admins to update bot behavior without redeploying code.
"""
from sqlalchemy import Column, String, BigInteger, JSON, ForeignKey, Integer, UniqueConstraint, Boolean, Unicode
from app.db.session import Base

class IntentConfig(Base):
    __tablename__ = "intent_configs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    
    # Intent identifier (e.g., 'GREETING', 'SALES_DEMO')
    intent_key = Column(String(50), nullable=False, index=True)
    
    # List of keywords used for detection
    keywords = Column(JSON, nullable=False)
    
    # Static response or template
    response_text = Column(Unicode(5000), nullable=True)
    
    # Optional metadata (e.g., CTA label, action)
    metadata_json = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, server_default="1")

    __table_args__ = (
        UniqueConstraint('intent_key', 'tenant_id', name='uq_intent_tenant'),
    )
