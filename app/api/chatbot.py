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
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode

from app.models.chat_message import ChatMessage

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
                "message": "Welcome back to GTD Service! How can I assist with your trade intelligence today?",
                "state": active_session.chat_state,
                "type": "CTA",
                "cta_label": "Book Demo",
                "action": "OPEN_LEAD_FORM",
                "conversation_status": active_session.conversation_mode,
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
        "message": "Welcome to GTD Service! Are you looking to import/export data or access our GTIS database? I’m here to assist you — please let me know how I can help.",
        "state": ChatState.START,
        "type": "CTA",
        "cta_label": "Book Demo",
        "action": "OPEN_LEAD_FORM",
        "conversation_status": ConversationMode.BOT,
    }


# ── 2. Message Exchange ───────────────────────────────────────────────
@router.post("/message", response_model=ChatMessageResponse)
def send_message(request: Request, msg_req: ChatMessageRequest, db: Session = Depends(get_db)):
    """
    Processes user messages and generates bot responses.
    Enforces conversation status gate — bot is blocked when in HUMAN mode.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required.")

    active_session = session_service.get_active_session(db, session_id)
    if not active_session:
        raise HTTPException(status_code=401, detail="Invalid session.")

    # ── Status Gate — bot must NEVER respond when session is CLOSED ──────
    if active_session.session_status == SessionStatus.CLOSED:
        msg = "This conversation has been closed. Thank you for reaching out."
        return {
            "sessionId": session_id,
            "message": msg,
            "type": ResponseType.MESSAGE,
            "state": active_session.chat_state,
            "conversation_status": active_session.session_status
        }

    # ── Status Gate — bot must NEVER respond when in HUMAN mode ─────────
    if active_session.conversation_mode == ConversationMode.HUMAN:
        msg = "Connecting you with an agent. Please wait..."
        # If already handled by agent, bot is silent
        if active_session.assigned_agent_id:
             return {
                "sessionId": session_id,
                "message": "You are now chatting with an agent.",
                "type": ResponseType.MESSAGE,
                "state": active_session.chat_state,
                "conversation_status": active_session.conversation_mode
            }
        
        session_service.save_message(db, active_session, msg_req.message, "user")
        return {
            "sessionId": session_id,
            "message": msg,
            "type": ResponseType.MESSAGE,
            "state": active_session.chat_state,
            "conversation_status": active_session.conversation_mode
        }

    # ── ConversationMode == "BOT" — normal AI processing ─────────────────
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
            "state": active_session.chat_state,
            "conversation_status": active_session.conversation_mode
        }

    # Basic Intelligence Flow
    result = ChatbotService.handle_message(db, active_session, user_message)
    
    return {
        "sessionId": session_id,
        "message": result["message"],
        "type": ResponseType.MESSAGE,
        "state": result["state"],
        "conversation_status": active_session.conversation_mode
    }

# ── 3. Chat History (Persistence) ─────────────────────────────────────
@router.get("/history", response_model=List[ChatMessageResponse])
def get_chat_history(request: Request, db: Session = Depends(get_db)):
    """
    Returns full message history for the current session to enable persistence.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        return []

    active_session = session_service.get_active_session(db, session_id)
    if not active_session:
        return []

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at_utc.asc())
        .all()
    )

    # Map database models to ChatMessageResponse schema
    history = []
    for m in messages:
        history.append({
            "sessionId": session_id,
            "message": m.message_text,
            "role": m.message_type, # Frontend expects 'role' for UI
            "state": active_session.chat_state, # Defaulting to current state
            "type": ResponseType.MESSAGE,
            "conversation_status": active_session.conversation_mode,
        })

    return history

# ── 4. Session Termination ────────────────────────────────────────────
@router.post("/session/end")
def end_session(request: Request, response: Response, db: Session = Depends(get_db)):
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        session_service.close_session(db, session_id)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "success"}
