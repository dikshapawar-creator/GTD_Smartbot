from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, text
from app.db.session import Base
from app.db.types import CleanUnicode


class BotConfig(Base):
    __tablename__ = "bot_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, unique=True)
    chatbot_name = Column(CleanUnicode(255), nullable=False, default="Smart Chatbot")
    chatbot_logo_url = Column(String(500), nullable=False, default="/static/logo.png")
    fab_tooltip = Column(CleanUnicode(255), nullable=False, default="Trade Support")
    welcome_text = Column(CleanUnicode(500), nullable=False, default="Welcome to Smart Chatbot.")

    
    # ── SaaS Branding ────────────────────────────────────────────────
    primary_color = Column(String(50), nullable=False, default="#2B2A9B")  # Brand Blue
    secondary_color = Column(String(50), nullable=False, default="#1e40af")
    font_family = Column(String(100), nullable=False, default="'Inter', sans-serif")
    
    updated_at = Column(DateTime, server_default=text("GETDATE()"), onupdate=text("GETDATE()"))
