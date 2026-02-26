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

    # JWT Settings
    JWT_SECRET_KEY: str = "super-secret-key-change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Session Settings
    SESSION_COOKIE_NAME: str = "chat_session"
    SESSION_EXPIRY_MINUTES: int = 60

    # CORS
    # We use Any to prevent Pydantic from crashing on internal JSON parsing
    # from environment variables. The validator will handle conversion.
    CORS_ORIGINS: Any = [
        "http://localhost:3000",
        "http://localhost:8000",
        "https://gtt-smartbot-frontend.vercel.app",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            # Handle JSON array string
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    pass
            # Handle comma-separated string
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, list):
            return v
        return ["http://localhost:3000"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
