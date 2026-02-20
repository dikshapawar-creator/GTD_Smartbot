"""
Chatbot API — Simplified Production Core.
Handles session initialization, messaging, and trade flow.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone

from app.core.dependencies import get_db
from app.core.config import settings
from app.services.chatbot import ChatbotService
from app.services import session_service, intent_service, greeting_handler
from app.services.intent_service import IntentType
from app.models.intent_config import IntentConfig
from app.schemas.chatbot import (
    ChatMessageRequest, ChatMessageResponse, 
    ConversationResponse, ResponseType, SessionInitResponse, ChatState
)

router = APIRouter(prefix="/chat", tags=["Chatbot"])

# ── 1. Session Initialization ──────────────────────────────────────────
@router.post("/session/init", response_model=SessionInitResponse)
def initialize_session(request: Request, response: Response, db: Session = Depends(get_db)):
    """
    Initializes or restores a chatbot session.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    
    if session_id:
        active_session = session_service.get_active_session(db, session_id)
        if active_session:
            return {
                "session_token": active_session.session_id,
                "message": "Welcome back! How can I help you today?",
                "state": active_session.chat_state,
                "type": "CTA",
                "cta_label": "Book Demo",
                "action": "OPEN_LEAD_FORM"
            }

    # Extract client info for new session
    client_ip = request.client.host if request.client else "127.0.0.1"
    new_session = session_service.create_session(db, client_ip, "Unknown", "Unknown", "UTC")

    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=new_session.session_id,
        httponly=True,
        max_age=settings.SESSION_EXPIRY_MINUTES * 60
    )

    return {
        "session_token": new_session.session_id,
        "message": "Welcome! Are you looking to import or export data?",
        "state": ChatState.START,
        "type": "CTA",
        "cta_label": "Book Demo",
        "action": "OPEN_LEAD_FORM"
    }

# ── 2. Message Exchange ───────────────────────────────────────────────
@router.post("/message", response_model=ChatMessageResponse)
def send_message(request: Request, msg_req: ChatMessageRequest, db: Session = Depends(get_db)):
    """
    Processes user messages and generates bot responses.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required.")

    active_session = session_service.get_active_session(db, session_id)
    if not active_session:
        raise HTTPException(status_code=401, detail="Invalid session.")

    user_message = msg_req.message
    intent = intent_service.detect_intent(db, user_message)

    # Greeting Logic
    if intent == IntentType.GREETING:
        greet_result = greeting_handler.handle_greeting(db, active_session)
        session_service.save_message(db, active_session, user_message, "user")
        session_service.save_message(db, active_session, greet_result["message"], "bot")
        return {
            "sessionId": session_id,
            "message": greet_result["message"],
            "type": greet_result["type"],
            "state": active_session.chat_state
        }

    # Basic Intelligence Flow
    result = ChatbotService.handle_message(db, active_session, user_message)
    
    return {
        "sessionId": session_id,
        "message": result["message"],
        "type": ResponseType.MESSAGE,
        "state": result["state"]
    }

# ── 3. Session Termination ────────────────────────────────────────────
@router.post("/session/end")
def end_session(request: Request, response: Response, db: Session = Depends(get_db)):
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        session_service.expire_session(db, session_id)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "success"}
