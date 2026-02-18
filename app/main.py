import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logger import setup_logging
from app.db.session import init_db
from app.api.chatbot import router as chatbot_router
from app.api.leads import router as leads_router

# Initialize global logging
setup_logging()
logger = logging.getLogger(__name__)

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description="Production-grade Backend for EXIM Trade Intelligence Chatbot",
        version="2.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def on_startup():
        logger.info("Starting EXIM Chatbot system...")
        try:
            init_db()
            logger.info("System startup successful.")
        except Exception as e:
            logger.critical(f"System startup failed: {str(e)}")
            # Raise here if we want to prevent uvicorn from successfully starting up
            raise e

    # Routers
    app.include_router(chatbot_router)
    app.include_router(leads_router)

    @app.get("/health", tags=["Health"])
    def health_check():
        return {"status": "ok", "version": "2.1.0"}

    @app.get("/", tags=["Health"])
    def root():
        return {"app": settings.APP_NAME, "status": "active", "docs": "/docs"}

    return app

app = create_app()
