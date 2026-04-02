import logging
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.session import init_db
from app.api.chatbot import router as chatbot_router
from app.api.leads import router as leads_router
from app.api.intents import router as intents_router
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.roles import router as roles_router
from app.api.admin import router as admin_router
from app.api.sales import router as sales_router
from app.api.super_admin import router as super_admin_router
from app.api.admin_email import router as admin_email_router
from app.api.live_chat import router as live_chat_router
from app.services.live_chat_socket import init_live_chat_socket
from app.api.ws_chat import router as ws_router, legacy_router as legacy_ws_router
from app.api.bot_config import router as bot_config_router
from app.services.tenant_service import TenantService
from app.core.security import decode_access_token
from app.db.session import SessionLocal

# ── Simplified Production-Ready Logging ──────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup Logic ───────────────────────────────────────────────
    logger.info(f"Booting {settings.APP_NAME}...")
    try:
        import os
        import shutil
        # init_db() now handles its own internal error logging and suppression
        init_db()

        # Initialize live chat socket manager
        init_live_chat_socket()
        logger.info("Live chat socket manager initialized")
    except Exception as e:
        # This is a fallback in case init_db lets something through
        logger.error(f"Lifespan: Unhandled database initialization error: {e}")
        logger.warning("Lifespan: System entering Degraded Mode (DB unreachable).")

    yield
    # ── Shutdown Logic (if any) ─────────────────────────────────────
    logger.info("Shutting down application.")

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="EXIM Trade Intelligence Platform — Auth & AI Core",
        version="5.0.0",
        lifespan=lifespan,
        redirect_slashes=False
    )

    @app.middleware("http")
    async def traceback_middleware(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Traceback caught: {tb}")
            
            # Write to a file for easy reading by the agent
            try:
                with open("error_traceback.log", "a") as f:
                    f.write(f"\n{'='*40}\n")
                    f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                    f.write(f"PATH: {request.url.path}\n")
                    f.write(f"ERROR: {str(e)}\n")
                    f.write(tb)
            except:
                pass

            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "message": "Something went wrong. Please try again later."
                }
            )

    # ── Global Exception Handler (second safety net) ─────────────────────
    from fastapi.responses import JSONResponse as _JSONResponse
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        # Pass through standard HTTP errors (401, 403, 404, etc.) unchanged
        return _JSONResponse(status_code=exc.status_code, content={"success": False, "message": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        from fastapi.encoders import jsonable_encoder
        try:
            errors = jsonable_encoder(exc.errors())
        except Exception:
            errors = str(exc)
        return _JSONResponse(status_code=422, content={"success": False, "message": "Invalid request data.", "errors": errors})

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        import traceback
        logger.error(f"Global exception handler caught: {traceback.format_exc()}")
        return _JSONResponse(
            status_code=500,
            content={"success": False, "message": "Something went wrong. Please try again later."}
        )

    # ── Tenant Extraction Middleware ─────────────────────────────────
    # ── Tenant Rate Limiting (In-Memory) ──────────────────────────────
    from collections import defaultdict
    from datetime import datetime, timedelta
    
    # tenant_id -> list of timestamps
    tenant_request_history = defaultdict(list)
    RATE_LIMIT_WINDOW = 60  # seconds
    MAX_REQUESTS_PER_WINDOW = 300  # Conservative limit for SaaS tenants
    
    @app.middleware("http")
    async def tenant_middleware(request: Request, call_next):
        from app.core.tenant_resolver import TenantResolver
        from app.core.security import decode_access_token
        from app.models.auth import User

        # 1. Skip tenant check for health, root, documentation, and static files
        if request.url.path in ["/health", "/", "/debug-logs", "/debug-db", "/favicon.ico"] or \
           request.url.path.startswith("/static") or \
           request.url.path.startswith("/docs") or \
           request.url.path.startswith("/openapi.json") or \
           request.url.path.startswith("/redoc"):
            return await call_next(request)
        
        db = SessionLocal()
        tenant_id = None
        try:
            # 2. Identify Path Type
            public_paths = ["/chat", "/bot-config", "/leads/submit"]
            is_public = any(request.url.path.startswith(p) for p in public_paths)
            
            # 3. Resolve Tenant
            try:
                if is_public:
                    tenant_id = TenantResolver.resolve_public_tenant(db, request)
                else:
                    # Admin paths require JWT first
                    auth_header = request.headers.get("Authorization")
                    token = None
                    if auth_header and auth_header.startswith("Bearer "):
                        token = auth_header.split(" ")[1]
                    else:
                        token = request.query_params.get("token") # WebSockets

                    if token:
                        payload = decode_access_token(token)
                        if payload:
                            # Mock a user object with JWT claims for the resolver
                            user_id = payload.get("sub")
                            if user_id:
                                # We need enough of a user object for the resolver
                                user = db.query(User).filter(User.id == int(user_id)).first()
                                if user:
                                    # Attach JWT claims
                                    user._jwt_tenant_ids = payload.get("tenant_ids", [])
                                    user._jwt_primary_tenant_id = payload.get("primary_tenant_id") or payload.get("tenant_id")
                                    user._jwt_is_super_admin = payload.get("is_super_admin", False)
                                    
                                    tenant_id = TenantResolver.resolve_admin_tenant(db, request, user)
            
            except HTTPException as http_exc:
                # Re-raise explicit security blocks
                return JSONResponse(status_code=http_exc.status_code, content={"success": False, "message": http_exc.detail})
                
            # 5. Store in request state
            request.state.tenant_id = tenant_id
            
            # 6. Strict Path Protection (Final Check)
            # Exclusion list: health checks, core auth, static assets, and documentation
            exempt_paths = ["/health", "/", "/debug-logs", "/debug-db", "/favicon.ico"]
            is_exempt = request.url.path in exempt_paths or \
                        request.url.path.startswith("/auth") or \
                        request.url.path.startswith("/static") or \
                        request.url.path.startswith("/docs") or \
                        request.url.path.startswith("/openapi.json") or \
                        request.url.path.startswith("/redoc")
            
            if not tenant_id and not is_exempt:
                logger.error(f"SECURITY BLOCK: No tenant identified for {request.url.path}")
                return JSONResponse(
                    status_code=403, 
                    content={"success": False, "message": "Tenant requirement not met. Access denied."}
                )

            # 7. Rate Limiting (Public Only)
            if is_public and tenant_id:
                client_ip = request.client.host
                rate_limit_key = f"{tenant_id}:{client_ip}"
                
                now = datetime.now()
                window_start = now - timedelta(seconds=RATE_LIMIT_WINDOW)
                
                # Get or init history
                if rate_limit_key not in tenant_request_history:
                    tenant_request_history[rate_limit_key] = []
                
                history = tenant_request_history[rate_limit_key]
                tenant_request_history[rate_limit_key] = [ts for ts in history if ts > window_start]
                
                if len(tenant_request_history[rate_limit_key]) >= MAX_REQUESTS_PER_WINDOW:
                    logger.warning(f"RATE LIMIT: {rate_limit_key} exceeded limit.")
                    return JSONResponse(status_code=429, content={"success": False, "message": "Rate limit exceeded. Please try again later."})
                
                tenant_request_history[rate_limit_key].append(now)


            return await call_next(request)
        except Exception as e:
            logger.exception(f"Unhandled error in tenant_middleware: {str(e)}")
            return JSONResponse(status_code=500, content={"success": False, "message": "Internal server error during tenant resolution."})
        finally:
            db.close()



    # ── Request Logging Middleware ──────────────────────────────────

    # ── CORS Middleware (Outermost Layer — registered LAST, runs FIRST in LIFO) ──
    # SECURITY: Using specific origins instead of "*" to support allow_credentials=True
    # regex used to support Vercel dynamic preview URLs
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
        allow_origin_regex=settings.CORS_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # ── API Routes (Consolidated) ───────────────────────────────────
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(roles_router)
    app.include_router(chatbot_router)
    app.include_router(leads_router)
    app.include_router(live_chat_router)
    app.include_router(ws_router)
    app.include_router(legacy_ws_router)
    app.include_router(intents_router)
    app.include_router(admin_router)
    app.include_router(sales_router)
    app.include_router(bot_config_router)
    app.include_router(admin_email_router)
    app.include_router(super_admin_router)

    # Mount static files (search in app/static or root static/)
    import os
    from fastapi.staticfiles import StaticFiles
    # Mount static files (logos, etc.)
    # We prioritize app/static where database-uploaded logos are stored
    app_static = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(app_static):
        app.mount("/static", StaticFiles(directory=app_static), name="static")
    else:
        # Fallback to root static/ for local dev consistency
        root_static = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        if os.path.exists(root_static):
            app.mount("/static", StaticFiles(directory=root_static), name="static")

    # Health Checks
    @app.get("/health", tags=["System"])
    async def health():
        from app.db.session import keep_alive_ping
        db_ok = keep_alive_ping()
        return {
            "status": "healthy" if db_ok else "degraded",
            "database": "connected" if db_ok else "unreachable",
            "app": settings.APP_NAME,
            "version": "5.0.3"
        }

    @app.get("/debug-db", tags=["System"])
    async def debug_db():
        from app.db.session import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            configs = db.execute(text("SELECT tenant_id, chatbot_name, chatbot_logo_url FROM bot_config")).fetchall()
            tenants = db.execute(text("SELECT id, name, api_key, domain FROM tenants")).fetchall()
            return {
                "configs": [{"tenant_id": r[0], "chatbot_name": r[1], "chatbot_logo_url": r[2]} for r in configs],
                "tenants": [{"id": r[0], "name": r[1], "api_key": r[2], "domain": r[3]} for r in tenants]
            }

    @app.get("/debug-logs", tags=["System"])
    async def debug_logs():
        """Return some log records if possible."""
        import logging
        logger = logging.getLogger("app") # Or root
        # This is a bit hacky, but let's try to get info from the logger handlers
        return {"message": "Logs are sent to terminal. Check uvicorn output."}

    @app.get("/", tags=["System"])
    async def root():
        return {"message": "Chatbot API is active", "version": "5.0.0"}

    @app.get("/debug-t3", tags=["System"])
    async def debug_t3_test():
        from app.db.session import SessionLocal
        from app.models.intent_config import IntentConfig
        from sqlalchemy import text
        with SessionLocal() as db:
            all_intents = db.query(IntentConfig).all()
            return {
                "total_intents": len(all_intents),
                "intent_tenants": [i.tenant_id for i in all_intents],
                "intent_keys": [i.intent_key for i in all_intents]
            }

    return app

# Trigger reload for schema sync
app = create_app()
