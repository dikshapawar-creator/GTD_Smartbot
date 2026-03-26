from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, text, Text, DateTime, func
from app.db.session import Base


class EmailConfig(Base):
    __tablename__ = "email_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, unique=True, index=True)
    
    # ── SMTP Settings ──────────────────────────────────────────────────
    smtp_host = Column(String(255), nullable=False)
    smtp_port = Column(Integer, nullable=False, default=587)
    smtp_user = Column(String(255), nullable=False)
    smtp_password = Column(String(255), nullable=False)
    smtp_from_email = Column(String(255), nullable=False)
    smtp_from_name = Column(String(255), nullable=False, default="Chatbot Support")
    smtp_use_tls = Column(Boolean, default=True)
    smtp_use_ssl = Column(Boolean, default=False)

    # ── HTML Templates (The "Card Design") ──────────────────────────────
    # Using Text for large HTML content
    confirmation_template = Column(Text, nullable=True)
    reset_password_template = Column(Text, nullable=True)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
