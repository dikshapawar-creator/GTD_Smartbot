"""
IntentConfig model — Stores dynamic intent keywords and response templates.
Allows admins to update bot behavior without redeploying code.
"""
from sqlalchemy import Column, String, BigInteger, JSON
from app.db.session import Base

class IntentConfig(Base):
    __tablename__ = "intent_configs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    # Intent identifier (e.g., 'GREETING', 'SALES_DEMO')
    intent_key = Column(String(50), nullable=False, unique=True, index=True)
    
    # List of keywords used for detection
    keywords = Column(JSON, nullable=False)
    
    # Static response or template
    response_text = Column(String(1000), nullable=True)
    
    # Optional metadata (e.g., CTA label, action)
    metadata_json = Column(JSON, nullable=True)
