from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, text
from app.db.session import Base


class BotConfig(Base):
    __tablename__ = "bot_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, unique=True)
    chatbot_name = Column(String(255), nullable=False, default="GTD Support")
    chatbot_logo_url = Column(String(500), nullable=False, default="/static/logo.png")
    fab_tooltip = Column(String(255), nullable=False, default="Trade Support")
    welcome_text = Column(String(500), nullable=False, default="Welcome to GTD Service.")
    
    # ── SaaS Branding ────────────────────────────────────────────────
    primary_color = Column(String(50), nullable=False, default="#2563eb")  # GTD Blue
    secondary_color = Column(String(50), nullable=False, default="#1e40af")
    font_family = Column(String(100), nullable=False, default="'Inter', sans-serif")
    
    updated_at = Column(DateTime, server_default=text("GETDATE()"), onupdate=text("GETDATE()"))
