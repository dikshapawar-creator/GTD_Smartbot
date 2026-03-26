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
    # Force professional greeting (pinned to GTD Service / Tenant 1 flow)
    config = db.query(IntentConfig).filter(
        IntentConfig.intent_key == "GREETING",
        IntentConfig.tenant_id == chat_session.tenant_id
    ).first()

    # Fallback to generic if still not in DB
    response_text = config.response_text if (config and config.response_text) else "Hello! How can I help you today?"
    
    from app.services import session_service
    if not chat_session.has_greeted:
        chat_session.has_greeted = True
        db.commit()
        
        # Save greeting as bot message so it shows up in history & metrics
        session_service.save_message(db, chat_session, response_text, "bot")
        
        logger.info({"event": "greeting_sent", "session_id": chat_session.session_id, "first_time": True})
        return {"type": ResponseType.MESSAGE, "message": response_text}

    logger.info({"event": "greeting_sent", "session_id": chat_session.session_id, "first_time": False})
    return {"type": ResponseType.MESSAGE, "message": "How can I assist you further?"}
