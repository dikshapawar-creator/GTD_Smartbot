from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "GTD Service Intelligence"
    DATABASE_URL: str
    SECRET_KEY: str = "your-secret-key-here"
    DEBUG: bool = True

    # JWT Settings
    JWT_SECRET_KEY: str = "super-secret-key-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60        # 1 hour access tokens
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30          # 30 day refresh tokens

    # Session Settings
    SESSION_COOKIE_NAME: str = "chat_session"
    SESSION_EXPIRY_MINUTES: int = 60

    # CORS
    FRONTEND_ORIGIN: str = "http://localhost:3000"
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
