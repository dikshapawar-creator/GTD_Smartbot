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
    pool_size=20,            # Keep 20 warm connections in the pool at all times
    max_overflow=50,         # Allow up to 50 extra burst connections
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
    
    # ⚡ FIX: Render Emojis from SQL Server NVARCHAR Correctly
    try:
        import pyodbc
        if isinstance(dbapi_connection, pyodbc.Connection):
            # Tell pyodbc to handle Unicode / Emojis via raw utf-16le converters
            dbapi_connection.add_output_converter(pyodbc.SQL_WVARCHAR, lambda x: x.decode('utf-16le') if x is not None else None)
            dbapi_connection.add_output_converter(pyodbc.SQL_WCHAR, lambda x: x.decode('utf-16le') if x is not None else None)
            dbapi_connection.add_output_converter(pyodbc.SQL_WLONGVARCHAR, lambda x: x.decode('utf-16le') if x is not None else None)
    except ImportError:
        pass # pyodbc not installed/used
    except Exception as e:
        logger.warning(f"Could not configure pyodbc encoding: {e}")

@event.listens_for(engine, "checkout")
def on_checkout(dbapi_connection, connection_record, connection_proxy):
    """Called every time a connection is checked out from the pool."""
    pass  # pool_pre_ping handles validation; this is a hook for future use

def keep_alive_ping() -> bool:
    """Check database connectivity for health checks."""
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"Health Check: Database unreachable - {e}")
        return False

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
        from app.models.bot_config import BotConfig
        from app.models.email_config import EmailConfig

        logger.info("Database: Initialization started...")

        # 1. Test raw connectivity safely
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database: Connectivity verified.")

        # 2. Synchronize Schema with metadata refresh
        Base.metadata.create_all(bind=engine)

        # 2.5 Seed default BotConfig for the primary tenant if missing
        try:
            _session = SessionLocal()
            # Explicitly find the primary/first active tenant
            primary_tenant = _session.query(Tenant).filter(Tenant.id == 2).first() or \
                             _session.query(Tenant).filter(Tenant.is_active == True).first()
            
            if primary_tenant:
                tid = primary_tenant.id
                existing = _session.query(BotConfig).filter(BotConfig.tenant_id == tid).first()
                if not existing:
                    _session.add(BotConfig(
                        tenant_id=tid,
                        chatbot_name="GTD Support",
                        chatbot_logo_url="/static/logo.png",
                        fab_tooltip="Trade Support",
                        welcome_text="Welcome to GTD Service."
                    ))
                    _session.commit()
                    logger.info(f"Database: Seeded BotConfig for tenant {tid}.")
            _session.close()
        except Exception as e:
            logger.warning(f"Database: BotConfig seeding skipped — {e}")

        # 2.6 Seed default EmailConfig if missing
        try:
            _session = SessionLocal()
            primary_tenant = _session.query(Tenant).filter(Tenant.id == 2).first() or \
                             _session.query(Tenant).filter(Tenant.is_active == True).first()
            
            if primary_tenant:
                tid = primary_tenant.id
                existing_email = _session.query(EmailConfig).filter(EmailConfig.tenant_id == tid).first()
                if not existing_email:
                    from app.services.email_service import CONFIRMATION_EMAIL_TEMPLATE, RESET_PASSWORD_EMAIL_TEMPLATE
                    _session.add(EmailConfig(
                        tenant_id=tid,
                        smtp_host=settings.SMTP_HOST,
                        smtp_port=settings.SMTP_PORT,
                        smtp_user=settings.SMTP_USER,
                        smtp_password=settings.SMTP_PASSWORD,
                        smtp_from_email=settings.SMTP_FROM_EMAIL,
                        smtp_from_name=settings.SMTP_FROM_NAME,
                        smtp_use_tls=settings.SMTP_USE_TLS,
                        smtp_use_ssl=settings.SMTP_USE_SSL,
                        confirmation_template=CONFIRMATION_EMAIL_TEMPLATE,
                        reset_password_template=RESET_PASSWORD_EMAIL_TEMPLATE
                    ))
                    _session.commit()
                    logger.info(f"Database: Seeded EmailConfig for tenant {tid}.")
            _session.close()
        except Exception as e:
            logger.warning(f"Database: EmailConfig seeding skipped — {e}")
        
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
            # 1. Tenants table metadata
            for col, col_type in [("api_key", "NVARCHAR(255)"), ("domain", "NVARCHAR(255)"), ("tenant_key", "NVARCHAR(100)")]:
                check_col = conn.execute(text(
                    f"SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'tenants' AND COLUMN_NAME = '{col}'"
                )).fetchone()
                if not check_col:
                    logger.info(f"Database: Adding {col} to tenants...")
                    conn.execute(text(f"ALTER TABLE tenants ADD {col} {col_type} NULL"))
                    try:
                        conn.execute(text(f"CREATE UNIQUE INDEX ux_tenants_{col} ON tenants({col}) WHERE {col} IS NOT NULL"))
                    except Exception as e:
                        logger.warning(f"Database: Could not create unique index on tenants({col}): {e}")

            # 2. Add tenant_id to all target tables
            target_tables = [
                "leads", "lead_status_history", "chat_sessions", "chat_messages", 
                "intent_configs", "blocked_visitors", "roles", "refresh_tokens", "password_resets"
            ]
            for table in target_tables:
                check_tenant = conn.execute(text(
                    f"SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{table}' AND COLUMN_NAME = 'tenant_id'"
                )).fetchone()
                if not check_tenant:
                    logger.info(f"Database: Adding tenant_id to {table}...")
                    conn.execute(text(f"ALTER TABLE {table} ADD tenant_id INT NOT NULL DEFAULT 2"))
                    try:
                        conn.execute(text(f"CREATE INDEX ix_{table}_tenant_id ON {table}(tenant_id)"))
                    except Exception as e:
                        logger.warning(f"Database: Could not create index on {table}(tenant_id): {e}")

            # 3. Specific table enhancements
            # Leads session_id column
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

            # 5. Data Migration: Ensure consistency
            for table in target_tables:
                 conn.execute(text(f"UPDATE {table} SET tenant_id = {settings.DEFAULT_TENANT_ID} WHERE tenant_id IS NULL OR tenant_id = 0"))
            
            # 6. Chat session enrichment columns
            check_is_lead = conn.execute(text(
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'chat_sessions' AND COLUMN_NAME = 'is_lead'"
            )).fetchone()
            if not check_is_lead:
                logger.info("Database: Adding is_lead to chat_sessions...")
                conn.execute(text("ALTER TABLE chat_sessions ADD is_lead BIT NOT NULL DEFAULT 0"))

            # 6.5 IntentConfig is_active column
            check_is_active = conn.execute(text(
                "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'intent_configs' AND COLUMN_NAME = 'is_active'"
            )).fetchone()
            if not check_is_active:
                logger.info("Database: Adding is_active to intent_configs...")
                conn.execute(text("ALTER TABLE intent_configs ADD is_active BIT NOT NULL DEFAULT 1"))

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

            # 7. Seed Default Tenant API Key if missing
            default_tenant = conn.execute(text(f"SELECT id FROM tenants WHERE id = {settings.DEFAULT_TENANT_ID}")).fetchone()
            if default_tenant:
                conn.execute(text(f"UPDATE tenants SET api_key = 'tenant_abc123', domain = 'localhost' WHERE id = {settings.DEFAULT_TENANT_ID} AND api_key IS NULL"))
            
            # 7.5 Retroactively populate tenant_key if NULL
            tenants_without_key = conn.execute(text("SELECT id, name FROM tenants WHERE tenant_key IS NULL")).fetchall()
            if tenants_without_key:
                from app.core.security import generate_tenant_key
                for tid, tname in tenants_without_key:
                    # Generate a key (e.g., 'gtd_7a2b9c' or just '7a2b9c')
                    new_key = generate_tenant_key(length=8)
                    logger.info(f"Database: Retroactively assigning key {new_key} to tenant {tid}")
                    conn.execute(text("UPDATE tenants SET tenant_key = :key WHERE id = :id"), {"key": new_key, "id": tid})

            # 8. Force Global Re-login
            conn.execute(text("UPDATE users SET token_version = 5 WHERE token_version < 5"))

            # 9. Bot Config Branding Cleanup & Logo Sync (High-Fidelity Avatar)
            logger.info("Database: cleaning up bot_config branding and syncing logos...")
            # We use the specific high-fidelity logo uploaded today for tenant 2 as the new standard
            logo_path = "/static/logos/chatbot_logo_2_67e79328.png"
            conn.execute(text(f"""
                UPDATE bot_config 
                SET chatbot_name = 'GTD Support',
                    chatbot_logo_url = '{logo_path}',
                    fab_tooltip = 'Trade Support',
                    welcome_text = 'Welcome to GTD Service.',
                    primary_color = '#2563eb',
                    secondary_color = '#1e40af',
                    font_family = 'Inter, sans-serif'
                WHERE tenant_id IS NOT NULL
            """))

            # 7. Session ID/UUID mismatch is handled at runtime in live_chat.py and ws_chat.py
            # (Migration blocked by FK constraint from chat_messages → chat_sessions.session_id)
            
    except Exception as e:
        logger.error(f"Database: Hot-fix failed - {e}")

        # DO NOT re-raise in development/startup so the app can boot
        # and provide health status or allow manual diagnostics via API.
