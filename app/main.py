import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
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
from app.api.live_chat import router as live_chat_router
from app.api.ws_chat import router as ws_router, legacy_router as legacy_ws_router
from app.api.bot_config import router as bot_config_router
from app.services.live_chat_socket import init_live_chat_socket

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
            # ── Log full details server-side ONLY ──────────────────────────
            logger.error(f"Traceback caught: {tb}")
            from fastapi.responses import JSONResponse
            # ── NEVER expose raw SQL / traceback to the client ─────────────
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
        return _JSONResponse(status_code=422, content={"success": False, "message": "Invalid request data.", "errors": exc.errors()})

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        import traceback
        logger.error(f"Global exception handler caught: {traceback.format_exc()}")
        return _JSONResponse(
            status_code=500,
            content={"success": False, "message": "Something went wrong. Please try again later."}
        )

    # ── Request Logging Middleware ──────────────────────────────────
    # NOTE: Registered BEFORE CORSMiddleware so CORS wraps everything (LIFO order).
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        origin = request.headers.get('origin')
        logger.info(f"REQ: {request.method} {request.url} | ORIGIN: {origin}")
        try:
            response = await call_next(request)
            logger.info(f"RES: {response.status_code}")
            return response
        except Exception as e:
            logger.exception(f"Unhandled exception during request: {e}")
            raise e

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

    # Mount static files for uploaded logos
    import os
    from fastapi.staticfiles import StaticFiles
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

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

    return app

app = create_app()
