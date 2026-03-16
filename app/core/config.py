from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Union, Any, Optional
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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440 # 24 hours for better session persistence
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    @model_validator(mode='after')
    def sync_secrets(self) -> 'Settings':
        # Ensure JWT_SECRET_KEY matches SECRET_KEY if provided in .env
        if self.SECRET_KEY != "your-secret-key-here":
            self.JWT_SECRET_KEY = self.SECRET_KEY
        return self

    # Session Settings
    SESSION_COOKIE_NAME: str = "chat_session"
    SESSION_EXPIRY_MINUTES: int = 60

    # CORS
    # Defined as strict string to bypass Pydantic V2 list JSON parsing errors from .env
    CORS_ORIGINS: str = (
        "http://localhost:3000,http://localhost:8000,https://gtt-smartbot-frontend.vercel.app,"
        "https://gtdservice.com,https://www.gtdservice.com"
    )
    # Regex matches: Vercel preview URLs + any additional client website domains
    # Add client site domains to .env as CORS_ORIGIN_REGEX to avoid code redeployment
    CORS_ORIGIN_REGEX: str = r"https://gtt-smartbot-frontend-.*\.vercel\.app"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
