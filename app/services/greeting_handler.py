"""
GreetingHandler — Manages professional greeting responses via database templates.
"""
import logging
from sqlalchemy.orm import Session
from app.models.chat_session import ChatSession
from app.models.intent_config import IntentConfig
from app.schemas.chatbot import ResponseType

logger = logging.getLogger(__name__)

def handle_greeting(db: Session, chat_session: ChatSession) -> dict:
    """
    Handles a greeting message using the template stored in intent_configs.
    """
    # Fetch response from DB
    config = db.query(IntentConfig).filter(IntentConfig.intent_key == "GREETING").first()
    
    # Fallback to hardcoded if not in DB (safety)
    response_text = config.response_text if config else "Hello! Welcome to GTD Service. How can I assist you today?"
    
    if not chat_session.has_greeted:
        chat_session.has_greeted = True
        db.commit()
        
        logger.info({"event": "greeting_sent", "session_id": chat_session.session_id, "first_time": True})
        return {"type": ResponseType.MESSAGE, "message": response_text}

    logger.info({"event": "greeting_sent", "session_id": chat_session.session_id, "first_time": False})
    return {"type": ResponseType.MESSAGE, "message": "How can I assist you further?"}
