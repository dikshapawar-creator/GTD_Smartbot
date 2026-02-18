import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from app.db.session import Base

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    # Native UUID as foreign key
    lead_id = Column(UNIQUEIDENTIFIER, ForeignKey("leads.id"), nullable=False)
    message = Column(Text, nullable=False)
    sender = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
