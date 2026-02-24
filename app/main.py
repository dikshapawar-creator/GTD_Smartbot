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
        init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}")
        raise e
    yield
    # ── Shutdown Logic (if any) ─────────────────────────────────────
    logger.info("Shutting down application.")

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="EXIM Trade Intelligence Platform — Auth & AI Core",
        version="5.0.0",
        lifespan=lifespan
    )

    # ── CORS Configuration ──────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )


    # ── Request Logging Middleware ──────────────────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.info(f"Incoming request: {request.method} {request.url} | Origin: {request.headers.get('origin')}")
        response = await call_next(request)
        logger.info(f"Response status: {response.status_code}")
        return response

    # ── API Routes (Consolidated) ───────────────────────────────────
    app.include_router(auth_router)
    app.include_router(users_router)
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
        return {"status": "healthy", "app": settings.APP_NAME}

    @app.get("/", tags=["System"])
    async def root():
        return {"message": "Chatbot API is active", "docs": "/docs"}

    return app

app = create_app()
