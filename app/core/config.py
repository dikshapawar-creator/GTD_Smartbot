from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "EXIM Chatbot"
    DATABASE_URL: str
    SECRET_KEY: str = "your-secret-key-here"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Session management
    SESSION_EXPIRY_MINUTES: int = 30
    SESSION_COOKIE_NAME: str = "chat_session"

    # IP Geolocation (ipapi.co — free tier, no key required)
    IP_API_URL: str = "https://ipapi.co/{ip}/json/"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
