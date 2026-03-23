import logging
from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from sqlalchemy.exc import OperationalError
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Enterprise-Grade SQL Server Connection — Always-On ─────────────────────
#
# Architecture:
#   Frontend (Vercel) → Backend Server (103.30.72.94) → SQL Server (103.30.72.94:1433)
#
# The DATABASE_URL points to the REMOTE SQL Server IP — never localhost.
# Connection resilience is layered at 3 levels:
#   1. ODBC Driver level  → ConnectRetryCount/Interval (URL params + connect_args)
#   2. SQLAlchemy pool    → pool_pre_ping + pool_recycle keeps pool healthy
#   3. Application level  → get_db_with_retry() retries on OperationalError
#
engine = create_engine(
    settings.DATABASE_URL,
    # ── Pool Settings ────────────────────────────────────────────────────
    pool_pre_ping=True,      # Validate connection health before every use
    pool_recycle=1200,       # Recycle every 20 min (SQL Server drops idle at ~30 min)
    pool_size=10,            # Keep 10 warm connections in the pool at all times
    max_overflow=20,         # Allow up to 20 extra burst connections
    pool_timeout=30,         # Max queue wait before raising error
    # ── ODBC Connection Resiliency ───────────────────────────────────────
    # Microsoft ODBC Driver 18 built-in retry — handles TCP drops at driver level.
    # ConnectRetryCount/Interval also embedded in DATABASE_URL for dual enforcement.
    connect_args={
        "ConnectRetryCount": 3,      # Retry up to 3x on broken TCP connection
        "ConnectRetryInterval": 10,  # 10s between driver-level retries
        "Connection Timeout": 30,    # Max 30s for initial connection establishment
        "TrustServerCertificate": "yes",  # Required for non-Azure SQL Server
    },
    echo=False,
)

# ── Connection Event Listener ─────────────────────────────────────────────
# Logs every NEW physical connection to the pool so you can see in journalctl
# exactly when SQLAlchemy reconnects after a drop.
@event.listens_for(engine, "connect")
def on_connect(dbapi_connection, connection_record):
    logger.info("Database: New physical connection established to SQL Server.")

@event.listens_for(engine, "checkout")
def on_checkout(dbapi_connection, connection_record, connection_proxy):
    """Called every time a connection is checked out from the pool."""
    pass  # pool_pre_ping handles validation; this is a hook for future use

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    Standard FastAPI dependency — yields a DB session.
    Uses pool_pre_ping to validate connection health before each request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_with_retry():
    """
    Hardened DB dependency with application-level retry on connection failure.
    Use this for critical endpoints (e.g. /chat/session/init) that must not
    fail due to transient SQL Server connection drops.
    """
    import time
    db = SessionLocal()
    try:
        # Explicit health check before yielding
        db.execute(text("SELECT 1"))
        yield db
    except OperationalError:
        logger.warning("Database: Connection check failed, disposing pool and retrying...")
        db.close()
        engine.dispose()
        time.sleep(0.5)
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    finally:
        try:
            db.close()
        except Exception:
            pass


def keep_alive_ping() -> bool:
    """
    Utility: ping the database to keep the connection pool warm.
    Call this from the health check endpoint or a background scheduler.
    Returns True if the DB is reachable, False otherwise.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning(f"Database: Keep-alive ping failed — {e}")
        return False



def init_db():
    """
    Initializes the database, creates tables, and tests the connection.
    Designed to log errors instead of crashing the application startup flow.
    """
    try:
        # Import models here to ensure they are registered with Base.metadata
        from app.models.lead import Lead
        from app.models.chat_session import ChatSession
        from app.models.chat_message import ChatMessage
        from app.models.intent_config import IntentConfig
        from app.models.blocked import BlockedVisitor
        from app.models.auth import User, Role, Tenant, RefreshToken, PasswordReset, AuditLog

        logger.info("Database: Initialization started...")

        # 1. Test raw connectivity safely
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database: Connectivity verified.")

        # 2. Synchronize Schema with metadata refresh
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

            # Leads session_id column (Lead <-> Chat linkage)
            check_session_id = conn.execute(text(
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'leads' AND COLUMN_NAME = 'session_id'"
            )).fetchone()
            if not check_session_id:
                logger.info("Database: Adding session_id to leads...")
                conn.execute(text("ALTER TABLE leads ADD session_id VARCHAR(36) NULL"))
                try:
                    conn.execute(text("CREATE INDEX ix_leads_session_id ON leads(session_id)"))
                except Exception as e:
                    logger.warning(f"Database: Could not create index on leads(session_id): {e}")

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
            
            # 8. is_lead column for chat_sessions (Lead <-> Chat linkage)
            check_is_lead = conn.execute(text(
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'chat_sessions' AND COLUMN_NAME = 'is_lead'"
            )).fetchone()
            if not check_is_lead:
                logger.info("Database: Adding is_lead to chat_sessions...")
                conn.execute(text("ALTER TABLE chat_sessions ADD is_lead BIT NOT NULL DEFAULT 0"))

            # Lead Details columns for chat_sessions
            for col, col_type in [
                ("lead_name", "NVARCHAR(255)"),
                ("lead_email", "NVARCHAR(255)"),
                ("lead_phone", "NVARCHAR(50)"),
                ("lead_company", "NVARCHAR(255)")
            ]:
                check_col = conn.execute(text(
                    f"SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'chat_sessions' AND COLUMN_NAME = '{col}'"
                )).fetchone()
                if not check_col:
                    logger.info(f"Database: Adding {col} to chat_sessions...")
                    conn.execute(text(f"ALTER TABLE chat_sessions ADD {col} {col_type} NULL"))

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
