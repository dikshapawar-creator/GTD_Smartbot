from pydantic import BaseModel
from typing import Optional


from pydantic import BaseModel, Field

class BotConfigResponse(BaseModel):
    chatbot_name: Optional[str] = Field(default="GTD Support")
    chatbot_logo_url: Optional[str] = Field(default="/static/logo.png")
    fab_tooltip: Optional[str] = Field(default="Trade Support")
    welcome_text: Optional[str] = Field(default="Welcome to GTD Service.")
    primary_color: Optional[str] = Field(default="#2563eb")
    secondary_color: Optional[str] = Field(default="#1e40af")
    font_family: Optional[str] = Field(default="'Inter', sans-serif")

    class Config:
        from_attributes = True


class BotConfigUpdate(BaseModel):
    chatbot_name: Optional[str] = None
    chatbot_logo_url: Optional[str] = None
    fab_tooltip: Optional[str] = None
    welcome_text: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    font_family: Optional[str] = None
