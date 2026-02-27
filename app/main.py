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
from app.api.ws_chat import router as ws_router

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
    app.include_router(intents_router)
    app.include_router(admin_router)
    app.include_router(sales_router)

    # Health Checks
    @app.get("/health", tags=["System"])
    async def health():
        return {"status": "healthy", "app": settings.APP_NAME, "version": "5.0.3"}

    @app.get("/", tags=["System"])
    async def root():
        return {"message": "Chatbot API is active", "docs": "/docs"}

    return app

app = create_app()
