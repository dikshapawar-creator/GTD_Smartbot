import uuid
from sqlalchemy import Column, String, DateTime, func
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from app.db.session import Base

class Lead(Base):
    __tablename__ = "leads"

    # Using UNIQUEIDENTIFIER for SQL Server native UUID support
    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    company = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    trade_type = Column(String(50), nullable=True)
    country_interested = Column(String(255), nullable=True)
    product = Column(String(255), nullable=True)
    requirement_type = Column(String(255), nullable=True)
    status = Column(String(50), default="NEW")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
