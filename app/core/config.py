from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    APP_NAME: str = "EXIM Chatbot"
    DATABASE_URL: str
    SECRET_KEY: str = "your-secret-key-here"
    DEBUG: bool = True

    # CORS — replace with your actual frontend URL in production
    FRONTEND_ORIGIN: str = "http://localhost:3000"

    # CORS — replace with your actual frontend URL in production
    FRONTEND_ORIGIN: str = "http://localhost:3000"

    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
