import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

logger = logging.getLogger(__name__)

# robust engine creation with pool_pre_ping for better resilience
# The DSN should be correctly formatted in .env (e.g. mssql+pyodbc://...)
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,      # Checks connection health before use
    pool_recycle=1800,       # Recycle connections every 30 mins
    pool_size=10,            # Maintain a base pool of 10 connections
    max_overflow=20,         # Allow up to 20 additional "burst" connections
    pool_timeout=30,         # Wait up to 30s before timing out
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
        
        # 3. Hot-fix: Ensure tenant_id columns exist (SQL Server)
        _ensure_tenant_id_columns(engine)
        
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

def _ensure_tenant_id_columns(engine):
    """Adds tenant_id to leads and lead_status_history if missing."""
    try:
        with engine.begin() as conn:
            # Leads table
            check_leads = conn.execute(text(
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'leads' AND COLUMN_NAME = 'tenant_id'"
            )).fetchone()
            if not check_leads:
                logger.info("Database: Adding tenant_id to leads...")
                conn.execute(text("ALTER TABLE leads ADD tenant_id INT NOT NULL DEFAULT 1"))
                try:
                    conn.execute(text("CREATE INDEX ix_leads_tenant_id ON leads(tenant_id)"))
                except Exception as e:
                    logger.warning(f"Database: Could not create index on leads(tenant_id): {e}")

            # Lead status history table
            check_history = conn.execute(text(
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'lead_status_history' AND COLUMN_NAME = 'tenant_id'"
            )).fetchone()
            if not check_history:
                logger.info("Database: Adding tenant_id to lead_status_history...")
                conn.execute(text("ALTER TABLE lead_status_history ADD tenant_id INT NOT NULL DEFAULT 1"))
                try:
                    conn.execute(text("CREATE INDEX ix_lead_status_history_tenant_id ON lead_status_history(tenant_id)"))
                except Exception as e:
                    logger.warning(f"Database: Could not create index on lead_status_history(tenant_id): {e}")

            # 4. token_version column for JWT invalidation (users table)
            check_token_version = conn.execute(text(
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'users' AND COLUMN_NAME = 'token_version'"
            )).fetchone()
            if not check_token_version:
                logger.info("Database: Adding token_version to users...")
                conn.execute(text("ALTER TABLE users ADD token_version INT NOT NULL DEFAULT 1"))
            else:
                # Ensure no NULLs in existing token_version column
                conn.execute(text("UPDATE users SET token_version = 1 WHERE token_version IS NULL"))

            # 5. Data Migration: Ensure consistency (Temporary fix for transition)
            # Migrate any leads where tenant_id != DEFAULT_TENANT_ID if we are in a single-tenant assumed mode
            # Or just ensure all current leads are on tenant 1 for this specific user.
            conn.execute(text(f"UPDATE leads SET tenant_id = {settings.DEFAULT_TENANT_ID} WHERE tenant_id IS NULL OR tenant_id != {settings.DEFAULT_TENANT_ID}"))
            conn.execute(text(f"UPDATE lead_status_history SET tenant_id = {settings.DEFAULT_TENANT_ID} WHERE tenant_id IS NULL OR tenant_id != {settings.DEFAULT_TENANT_ID}"))
            
            # 6. Global Re-login (Force users to get new tenant IDs and stable secrets)
            # Only run this once relative to this fix (we can use a specific check if needed, 
            # but usually incrementing once is safe in this dev transition)
            # We'll check if any user has token_version < 2 (since our target is 2 or more)
            # Force increment token_version to 5 to be absolutely sure it happens now
            conn.execute(text("UPDATE users SET token_version = 5 WHERE token_version < 5"))

            # 7. Session ID/UUID mismatch is handled at runtime in live_chat.py and ws_chat.py
            # (Migration blocked by FK constraint from chat_messages → chat_sessions.session_id)
            
    except Exception as e:
        logger.error(f"Database: Hot-fix failed - {e}")

        # DO NOT re-raise in development/startup so the app can boot
        # and provide health status or allow manual diagnostics via API.
