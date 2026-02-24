import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

logger = logging.getLogger(__name__)

# robust engine creation with pool_pre_ping for better resilience
# The DSN should be correctly formatted in .env (e.g. mssql+pyodbc://...)
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db():
    """
    Initializes the database, creates tables, and tests the connection.
    Designed to log errors instead of crashing the application startup flow.
    """
    try:
        # Import models here to ensure they are registered with Base.metadata
        from app.models.lead import Lead
        from app.models.conversation import Conversation
        from app.models.chat_session import ChatSession
        from app.models.chat_message import ChatMessage
        from app.models.intent_config import IntentConfig
        from app.models.auth import User, Role, Tenant, RefreshToken, PasswordReset, AuditLog

        logger.info("Database: Initialization started...")

        # 1. Test raw connectivity safely
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database: Connectivity verified.")

        # 2. Synchronize Schema
        Base.metadata.create_all(bind=engine)
        logger.info("Database: Schema synchronized successfully.")

    except Exception as e:
        error_msg = str(e).lower()
        if "driver" in error_msg:
            logger.error("Database: CRITICAL - ODBC Driver missing or misconfigured.")
        elif "login fail" in error_msg or "access denied" in error_msg:
            logger.error("Database: CRITICAL - Invalid credentials or login failed.")
        elif "timeout" in error_msg or "08001" in error_msg:
            logger.error("Database: CRITICAL - SQL Server unreachable or connection timeout.")
        else:
            logger.error(f"Database: Initialization failed (Degraded Mode) - {str(e)}")

        # DO NOT re-raise in development/startup so the app can boot
        # and provide health status or allow manual diagnostics via API.
