import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

logger = logging.getLogger(__name__)

# Use fast_executemany for SQL Server performance if needed
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def init_db():
    try:
        # Import models here to ensure they are registered with Base.metadata
        from app.models.lead import Lead
        from app.models.conversation import Conversation
        from app.models.chat_session import ChatSession
        from app.models.chat_message import ChatMessage
        from app.models.intent_config import IntentConfig
        from app.models.auth import User, Role, Tenant, RefreshToken, PasswordReset, AuditLog
        
        logger.info("Connecting to database and creating tables...")
        Base.metadata.create_all(bind=engine)
        
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection successful.")
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        # In production, you might want to raise this or handle it based on criticality
        raise e
