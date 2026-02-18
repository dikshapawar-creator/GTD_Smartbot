from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "EXIM Chatbot"
    DATABASE_URL: str
    SECRET_KEY: str = "your-secret-key-here"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
