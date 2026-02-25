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
from app.services import session_service, intent_service, greeting_handler, lead_service
from app.services.intent_service import IntentType
from app.models.lead import Lead, LeadStatus
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
        "message": "Welcome to GTD Service. Please let me know how I can assist you.",
        "state": ChatState.START,
        "type": "CTA",
        "cta_label": "Book Demo",
        "action": "OPEN_LEAD_FORM",
        "conversation_status": ConversationMode.BOT,
    }


# ── 1. AGENT & SESSION GATES ──────────────────────────────────────────
@router.post("/message", response_model=ChatMessageResponse)
def send_message(request: Request, msg_req: ChatMessageRequest, db: Session = Depends(get_db)):
    """
    Overhauled Chatbot Logic:
    - Stops bot reply when agent is active (joins WS or sends message).
    - Hardcoded keyword-based intent handling.
    - Persistent Lead Capture (asks for missing fields).
    - Handoff logic (Bot silence after handover message).
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="Session required.")

    active_session = session_service.get_active_session(db, session_id)
    if not active_session:
        raise HTTPException(status_code=401, detail="Invalid session.")

    # A. Check for Agent activity or Handoff state (Silence Rule)
    # Return empty message if agent is joined, assigned, or recently spoke
    is_agent_active = (
        active_session.agent_joined or 
        active_session.assigned_agent_id is not None or 
        active_session.chat_state == ChatState.HANDOFF_SENT
    )

    if not is_agent_active:
        # Fallback check for last message from agent
        recent_agent_msg = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id,
            ChatMessage.message_type == "agent"
        ).order_by(ChatMessage.created_at_utc.desc()).first()
        if recent_agent_msg:
            active_session.agent_joined = True
            db.commit()
            is_agent_active = True

    if is_agent_active:
        # Save user message anyway for agent visibility
        session_service.save_message(db, active_session, msg_req.message, "user")
        return {
            "sessionId": session_id,
            "message": "", 
            "type": ResponseType.MESSAGE,
            "state": active_session.chat_state,
            "conversation_status": active_session.conversation_mode
        }

    # ── 2. INTENT & LEAD LOGIC ──────────────────────────────────────────
    user_message = msg_req.message
    # Save user message immediately to DB
    session_service.save_message(db, active_session, user_message, "user")
    
    intent = intent_service.detect_intent(db, user_message)
    current_state = active_session.chat_state
    bot_msg = ""
    
    # Check for Human/Representative request first (Priority 1)
    if intent == IntentType.HANDOFF:
        bot_msg = (
            "No problem.\n\n"
            "Please wait while I connect you with our expert."
        )
        active_session.chat_state = ChatState.HANDOFF_SENT
        db.commit()
        session_service.save_message(db, active_session, bot_msg, "bot")
        return {
            "sessionId": session_id,
            "message": bot_msg,
            "state": active_session.chat_state,
            "conversation_status": active_session.conversation_mode
        }

    # 2a. Handle Greetings
    if intent == IntentType.GREETING and current_state == ChatState.START:
        bot_msg = (
            "Hello 👋 Welcome to GTD Service.\n\n"
            "I help businesses find verified Import Export data, global buyers, and suppliers.\n\n"
            "How may I assist you today?"
        )
        session_service.save_message(db, active_session, bot_msg, "bot")
        return {
            "sessionId": session_id,
            "message": bot_msg,
            "type": ResponseType.MESSAGE,
            "state": ChatState.START,
            "conversation_status": active_session.conversation_mode
        }

    # 2b. Start Lead Flow (Intent: IMPORT/EXPORT or DEMO)
    if (intent in [IntentType.IMPORT_EXPORT, IntentType.DEMO]) and (current_state == ChatState.START):
        bot_msg = (
            "I will help you find the import export data.\n\n"
            "To assist you better, please share your details.\n\n"
            "May I know your Full Name?"
        )
        active_session.chat_state = ChatState.NAME
        db.commit()
        session_service.save_message(db, active_session, bot_msg, "bot")
        return {
            "sessionId": session_id,
            "message": bot_msg,
            "state": ChatState.NAME,
            "conversation_status": active_session.conversation_mode
        }

    # 2c. Lead Capture State Machine
    lead = None
    if active_session.lead_id:
        lead = db.query(Lead).filter(Lead.id == active_session.lead_id).first()

    def update_lead(field, value):
        nonlocal lead
        if not lead:
             placeholder_email = f"pending_{active_session.session_id}@gtdservice.local"
             lead = Lead(
                 name=value if field == "name" else "Visitor",
                 email=placeholder_email, # email is required in model
                 phone="Pending",
                 company="Pending",
                 status="IN_PROGRESS",
                 source="chatbot"
             )
             db.add(lead)
             db.flush()
             active_session.lead_id = str(lead.id)
        else:
            if field == "name": lead.name = value
            elif field == "company": lead.company = value
            elif field == "email": lead.email = value
            elif field == "phone": lead.phone = value
        db.commit()

    if current_state == ChatState.NAME:
        update_lead("name", user_message)
        active_session.chat_state = ChatState.COMPANY
        bot_msg = "Thank you.\n\nMay I know your Company Name?"
    elif current_state == ChatState.COMPANY:
        update_lead("company", user_message)
        active_session.chat_state = ChatState.EMAIL
        bot_msg = "Please share your Business Email."
    elif current_state == ChatState.EMAIL:
        update_lead("email", user_message)
        active_session.chat_state = ChatState.PHONE
        bot_msg = "May I have your Contact Number?"
    elif current_state == ChatState.PHONE:
        update_lead("phone", user_message)
        active_session.chat_state = ChatState.HANDOFF_SENT
        bot_msg = (
            "Thank you for sharing the details.\n\n"
            "Please wait while I connect you with our trade expert."
        )
    else:
        # Fallback if unknown state or unknown intent while in flow
        bot_msg = "I am not sure I understand. How else can I assist you with your trade needs?"

    db.commit()
    session_service.save_message(db, active_session, bot_msg, "bot")
    return {
        "sessionId": session_id,
        "message": bot_msg,
        "state": active_session.chat_state,
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
