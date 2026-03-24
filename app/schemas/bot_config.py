from pydantic import BaseModel
from typing import Optional


class BotConfigResponse(BaseModel):
    chatbot_name: str = "GTD Support"
    chatbot_logo_url: str = "/logo.png"
    fab_tooltip: str = "Trade Support"
    welcome_text: str = "Welcome to GTD Service."

    class Config:
        from_attributes = True


class BotConfigUpdate(BaseModel):
    chatbot_name: Optional[str] = None
    chatbot_logo_url: Optional[str] = None
    fab_tooltip: Optional[str] = None
    welcome_text: Optional[str] = None
