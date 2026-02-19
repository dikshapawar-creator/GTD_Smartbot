import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logger import setup_logging
from app.db.session import init_db
from app.api.session import router as session_router
from app.api.chatbot import router as chatbot_router
from app.api.leads import router as leads_router
from app.api.admin import router as admin_router

# Initialize global logging
setup_logging()
logger = logging.getLogger(__name__)

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="Enterprise Chatbot Backend with SQL Session Authority",
        version="3.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS configuration — ensure allow_credentials=True for cookies
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], # In production, replace with specific frontend URL
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup():
        logger.info({
            "event": "startup",
            "message": "Booting EXIM Enterprise Chatbot system",
            "app_name": settings.APP_NAME
        })
        try:
            init_db()
            logger.info({"event": "startup_success", "db": "initialized"})
        except Exception as e:
            logger.critical({"event": "startup_failed", "error": str(e)})
            raise e

    # Routers
    # Note: chatbot_router and session_router share /chat prefix logic
    app.include_router(session_router)
    app.include_router(chatbot_router)
    app.include_router(leads_router)
    app.include_router(admin_router)

    @app.get("/health", tags=["Health"])
    def health_check():
        return {"status": "ok", "version": "3.0.0"}

    @app.get("/", tags=["Health"])
    def root():
        return {"app": settings.APP_NAME, "status": "active", "docs": "/docs"}

    return app

app = create_app()
