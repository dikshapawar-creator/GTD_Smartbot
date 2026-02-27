from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Union, Any
import json


class Settings(BaseSettings):
    APP_NAME: str = "GTD Service Intelligence"
    DATABASE_URL: str
    SECRET_KEY: str = "your-secret-key-here"
    DEBUG: bool = True
    IP_API_URL: str = "https://ipapi.co/{ip}/json/"
    ADMIN_SETUP_TOKEN: str
    DEFAULT_TENANT_ID: int = 2

    # JWT Settings
    JWT_SECRET_KEY: str = "super-secret-key-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Session Settings
    SESSION_COOKIE_NAME: str = "chat_session"
    SESSION_EXPIRY_MINUTES: int = 60

    # CORS
    # Defined as strict string to bypass Pydantic V2 list JSON parsing errors from .env
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://localhost:8000,https://gtt-smartbot-frontend.vercel.app"
    )
    CORS_ORIGIN_REGEX: str = r"https://gtt-smartbot-frontend-.*\.vercel\.app"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
