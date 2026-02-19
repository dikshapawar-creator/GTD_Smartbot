"""
Chatbot API — Refactored for Enterprise Session Authority and Dynamic Intent-based Responses.
Uses SQL-based intent configurations (MESSAGE/CTA) and secures sessions via HTTP-only cookies.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.dependencies import get_db
from app.core.config import settings
from app.services.chatbot import ChatbotService
from app.services import session_service, rate_limit_service, intent_service, greeting_handler
from app.services.intent_service import IntentType
from app.models.intent_config import IntentConfig
from app.schemas.chatbot import ChatMessageRequest, ChatMessageResponse, ConversationResponse, ResponseType

router = APIRouter(prefix="/chat", tags=["Chatbot"])

@router.post("/message", response_model=ChatMessageResponse, summary="Send a message to the chatbot")
def send_message(request: Request, msg_req: ChatMessageRequest, db: Session = Depends(get_db)):
    """
    Enterprise Chat Message Handler with Dynamic Intent Detection.
    """
    # 1. Retrieve and validate session
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="No active session found. Please initialize session.")

    # 2. Rate Limiting (Anti-Abuse)
    if rate_limit_service.is_rate_limited(session_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Please slow down.")

    # 3. Validate and track session activity
    active_session = session_service.get_active_session(db, session_id)
    if not active_session:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")

    # 4. Intent Detection Layer (SQL-backed)
    user_message = msg_req.message
    intent = intent_service.detect_intent(db, user_message)

    # A. Handle Greeting Intent
    if intent == IntentType.GREETING:
        greet_result = greeting_handler.handle_greeting(db, active_session)
        session_service.save_message(db, active_session, user_message, "user")
        session_service.save_message(db, active_session, greet_result["message"], "bot")
        
        return {
            "sessionId": session_id,
            "message": greet_result["message"],
            "type": greet_result["type"],
            "state": active_session.chat_state,
            "intent": intent.value,
            "has_greeted": active_session.has_greeted
        }

    # B. Handle Sales/Demo Intent (Automatic CTA with dynamic config)
    if intent == IntentType.SALES_DEMO:
        # Fetch CTA config from SQL
        config = db.query(IntentConfig).filter(IntentConfig.intent_key == "SALES_DEMO").first()
        
        message = config.response_text if config else "I’d be grateful to help you with that. Please book a demo so we can guide you properly."
        meta = config.metadata_json if config else {"cta_label": "Book Demo", "action": "OPEN_LEAD_FORM"}
        
        session_service.save_message(db, active_session, user_message, "user")
        session_service.save_message(db, active_session, message, "bot")
        
        return {
            "sessionId": session_id,
            "message": message,
            "type": ResponseType.CTA,
            "cta_label": meta.get("cta_label", "Book Demo"),
            "action": meta.get("action", "OPEN_LEAD_FORM"),
            "state": active_session.chat_state,
            "intent": intent.value,
            "has_greeted": active_session.has_greeted
        }

    # 5. Process Business Flow (Trade Flow)
    result = ChatbotService.handle_message(db, active_session, user_message)
    
    return {
        "sessionId": session_id,
        "message": result["message"],
        "type": ResponseType.MESSAGE,
        "state": result["state"],
        "intent": intent.value,
        "has_greeted": active_session.has_greeted
    }


@router.get("/history", response_model=List[ConversationResponse])
def get_chat_history(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100)
):
    """
    Paginated chat history for the current session.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="No active session found.")

    offset = (page - 1) * limit
    
    from app.models.chat_message import ChatMessage
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at_utc.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "id": m.id,
            "lead_id": m.session_id,
            "message": m.message_text,
            "sender": m.message_type,
            "timestamp": m.created_at_utc
        } for m in messages
    ]
