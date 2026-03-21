import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.core.dependencies import get_db
from app.core.config import settings
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode

from app.models.chat_message import ChatMessage
from app.models.blocked import BlockedVisitor

logger = logging.getLogger(__name__)
from app.services.chatbot import ChatbotService
from app.services import session_service, intent_service, greeting_handler, lead_service
from app.core import utils
from app.services.intent_service import IntentType
from app.models.lead import Lead, LeadStatus
from app.models.intent_config import IntentConfig
from app.schemas.chatbot import (
    ChatMessageRequest, ChatMessageResponse, 
    ResponseType, SessionInitResponse, SessionInitRequest, ChatState
)

router = APIRouter(prefix="/chat", tags=["Chatbot"])

# ── 1. Session Initialization ──────────────────────────────────────────
@router.post("/session/init", response_model=SessionInitResponse)
async def initialize_session(request: Request, response: Response, init_req: Optional[SessionInitRequest] = None, db: Session = Depends(get_db)):
    """
    Initializes or restores a chatbot session.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    
    if session_id:
        active_session = session_service.get_active_session(db, session_id)
        # Verify session is truly active and exists
        if active_session and active_session.session_status == SessionStatus.ACTIVE:
            return {
                "session_token": str(active_session.visitor_uuid),
                "message": "Welcome back to GTD Service! How can I assist with your trade intelligence today?",
                "state": active_session.chat_state,
                "type": "CTA",
                "cta_label": "Book Demo",
                "action": "OPEN_LEAD_FORM",
                "conversation_status": active_session.conversation_mode,
                "server_time_utc": datetime.now(timezone.utc)
            }

    # Extract client info for new session
    client_ip = utils.get_client_ip(request)
    meta = utils.get_visitor_metadata(request)
    fingerprint = utils.generate_visitor_fingerprint(client_ip, meta["user_agent"])

    # 🚨 SECURITY: Blocked Visitor Check - TEMPORARILY DISABLED FOR DEBUGGING
    # is_blocked = db.query(BlockedVisitor).filter(
    #     (BlockedVisitor.ip_address == client_ip) | 
    #     (BlockedVisitor.visitor_fingerprint == fingerprint)
    # ).first()
    
    # if is_blocked:
    #     logger.warning(
    #         f"Blocked access attempt from client_ip: {client_ip} | fingerprint: {fingerprint} "
    #         f"| reason: {is_blocked.reason}"
    #     )
    #     raise HTTPException(
    #         status_code=403, 
    #         detail="Your access has been restricted due to security policy violations."
    #     )

    # Real-time Geolocation
    from app.services import geo_service
    country, city, timezone_str = geo_service.lookup_ip_geo(client_ip)

    visitor_uuid_ext = init_req.visitor_uuid if init_req else None
    
    # Check if returning visitor with an ACTIVE session
    existing_session = None
    is_returning = False
    carry_over_lead_id = None
    
    if visitor_uuid_ext:
        logger.info(f"[SESSION_INIT] Looking for existing session for visitor_uuid: {visitor_uuid_ext}")
        
        # 🔥 ENTERPRISE: Consolidate any duplicate sessions first
        from app.api.live_chat import consolidate_visitor_sessions
        existing_session = consolidate_visitor_sessions(db, visitor_uuid_ext)
        
        if existing_session:
            logger.info(f"[SESSION_INIT] REUSING existing session {existing_session.session_id} for visitor {visitor_uuid_ext}")
            # Update activity timestamp
            existing_session.last_activity_utc = datetime.now(timezone.utc)
            existing_session.last_seen_at = datetime.now(timezone.utc)
            db.commit()
            new_session = existing_session
            is_returning = True
        else:
            logger.info(f"[SESSION_INIT] No active session found for visitor {visitor_uuid_ext}, checking for prior history")
            # 2. If no active session, check for ANY prior history to flag as returning
            # AND carry over their Lead ID if they have one
            prior_session = db.query(ChatSession).filter(
                ChatSession.visitor_uuid == visitor_uuid_ext,
                ChatSession.total_messages > 0,
                ChatSession.is_deleted == False
            ).order_by(ChatSession.started_at_utc.desc()).first()
            
            if prior_session:
                is_returning = True
                logger.info(f"[SESSION_INIT] Found prior session history for visitor {visitor_uuid_ext}")
                # Check for lead id in any of their past sessions
                session_with_lead = db.query(ChatSession).filter(
                    ChatSession.visitor_uuid == visitor_uuid_ext,
                    ChatSession.lead_id.isnot(None),
                    ChatSession.is_deleted == False
                ).order_by(ChatSession.started_at_utc.desc()).first()
                
                if session_with_lead:
                    carry_over_lead_id = session_with_lead.lead_id
                    logger.info(f"[SESSION_INIT] Returning visitor {visitor_uuid_ext} has previous lead_id {carry_over_lead_id}")
    else:
        logger.warning("[SESSION_INIT] No visitor_uuid provided in session initialization request")

    if not existing_session:
        logger.info(f"[SESSION_INIT] Creating NEW session for visitor {visitor_uuid_ext}")
        new_session = session_service.create_session(
            db, 
            ip_address=client_ip,
            country=country, 
            city=city, 
            timezone_str=timezone_str,
            user_agent=meta["user_agent"],
            browser=meta["browser"],
            os_name=meta["os"],
            device_type=meta["device_type"],
            fingerprint=fingerprint,
            tenant_id=settings.DEFAULT_TENANT_ID,
            visitor_uuid=visitor_uuid_ext,
            lead_id=carry_over_lead_id # 🔥 Identity Retention
        )
        logger.info(f"[SESSION_INIT] NEW session created: {new_session.session_id}")
    
    # 🚨 COMMIT BEFORE BROADCAST
    db.commit()

    # 🔥 Immediately broadcast to CRM
    from app.core.socket_manager import socket_manager
    from app.api.live_chat import format_session_for_crm
    
    session_item = format_session_for_crm(new_session)
    await socket_manager.broadcast_event(
        "NEW_CONVERSATION", 
        session_item
    )

    # Fetch professional greeting from DB for consistency
    if is_returning:
        greeting_res = {"message": "Welcome back 👋 How can I help today?"}
    else:
        greeting_res = greeting_handler.handle_greeting(db, new_session)

    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=new_session.session_id,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=settings.SESSION_EXPIRY_MINUTES * 60
    )

    return {
        "session_token": str(new_session.visitor_uuid),
        "message": greeting_res["message"],
        "state": ChatState.START,
        "type": "CTA",
        "cta_label": "Book Demo",
        "action": "OPEN_LEAD_FORM",
        "conversation_status": new_session.conversation_mode,
        "server_time_utc": datetime.now(timezone.utc)
    }


# ── 1. AGENT & SESSION GATES ──────────────────────────────────────────
@router.post("/message", response_model=ChatMessageResponse)
async def send_message(request: Request, msg_req: ChatMessageRequest, db: Session = Depends(get_db)):
    """
    Overhauled Chatbot Logic:
    - Stops bot reply when agent is active (joins WS or sends message).
    - Hardcoded keyword-based intent handling.
    - Persistent Lead Capture (asks for missing fields).
    - Handoff logic (Bot silence after handover message).
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)

    # Fallback: read session UUID from Authorization: Bearer <session_uuid>
    # This handles cross-origin requests where cookies are blocked by the browser
    if not session_id:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            bearer_val = auth_header[len('Bearer '):].strip()
            # Only accept UUIDs (no dots) — reject Admin JWTs which contain dots
            if bearer_val and '.' not in bearer_val:
                session_id = bearer_val  # Use UUID directly

    if not session_id:
        raise HTTPException(status_code=401, detail="Session required.")

    # 🔧 FIX: The session_id we get might be a visitor_uuid from the bearer token
    try:
        active_session = session_service.get_active_session(db, session_id)
        if not active_session:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
    except ValueError as e:
        # Handle invalid UUID format
        logger.error(f"Invalid session UUID format: {session_id}, error: {e}")
        raise HTTPException(status_code=401, detail="Invalid session format.")

    # A. Check for Agent activity or Handoff state (Silence Rule)
    is_agent_active = (
        active_session.agent_joined or 
        active_session.assigned_agent_id is not None or 
        active_session.chat_state == ChatState.HANDOFF_SENT or
        active_session.conversation_mode == ConversationMode.HUMAN
    )

    if not is_agent_active:
        # Fallback check for last message from agent
        recent_agent_msg = db.query(ChatMessage).filter(
            ChatMessage.session_id == active_session.session_id,
            ChatMessage.message_type == "agent"
        ).order_by(ChatMessage.created_at_utc.desc()).first()
        if recent_agent_msg:
            active_session.agent_joined = True
            active_session.conversation_mode = ConversationMode.HUMAN
            db.commit()
            is_agent_active = True

    if is_agent_active:
        # Save user message anyway for agent visibility
        session_service.save_message(db, active_session, msg_req.message, "user")
        db.commit() # COMMIT BEFORE BROADCAST
        
        # 🔥 Broadcast to agents
        from app.core.socket_manager import socket_manager
        await socket_manager.broadcast_event(
            "NEW_MESSAGE",
            {
                "session_id": str(active_session.visitor_uuid),
                "message": msg_req.message,
                "sender": "user",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )

        return {
            "sessionId": str(active_session.visitor_uuid),
            "message": "", 
            "type": ResponseType.MESSAGE,
            "state": active_session.chat_state,
            "conversation_status": active_session.conversation_mode,
            "server_time_utc": datetime.now(timezone.utc)
        }

    # ── 2. INTENT & LEAD LOGIC ──────────────────────────────────────────
    user_message = msg_req.message
    
    # Analytics: Spam Detection
    from app.services.spam_service import check_message_spam
    if check_message_spam(db, active_session, user_message):
        active_session.spam_flag = True
        active_session.session_status = SessionStatus.CLOSED
        db.commit()
        return {
            "sessionId": str(active_session.visitor_uuid),
            "message": "Security policy violation detected. Session closed.",
            "state": active_session.chat_state,
            "conversation_status": active_session.conversation_mode,
            "server_time_utc": datetime.now(timezone.utc)
        }

    # Analytics: Language Translation
    from app.services.language_service import detect_and_translate
    lang_code, translated_message = detect_and_translate(user_message)
    if not active_session.language or active_session.language == "en":
        active_session.language = lang_code
        db.commit()

    # Save user message immediately to DB
    session_service.save_message(db, active_session, user_message, "user")
    
    # Analytics: Lead Scoring (Evaluate translated message)
    from app.services.scoring_service import update_session_score
    active_session = update_session_score(db, active_session, translated_message)
    
    if active_session.lead_status == "Hot":
        # Placeholder for smart sales alert
        print(f"🔥 HOT LEAD DETECTED: Session {active_session.session_id}")

    intent = intent_service.detect_intent(db, translated_message)
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
        db.commit() # COMMIT BEFORE BROADCAST
        
        #  Broadcast handoff signal
        from app.core.socket_manager import socket_manager
        await socket_manager.broadcast_event(
            "NEW_MESSAGE",
            {
                "session_id": str(active_session.visitor_uuid),
                "message": user_message,
                "sender": "user",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        await socket_manager.broadcast_event(
            "NEW_MESSAGE",
            {
                "session_id": str(active_session.visitor_uuid),
                "message": bot_msg,
                "sender": "bot",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        
        return {
            "sessionId": str(active_session.visitor_uuid),
            "message": bot_msg,
            "state": active_session.chat_state,
            "conversation_status": active_session.conversation_mode,
            "server_time_utc": datetime.now(timezone.utc)
        }

    # Helper function to broadcast messages and return response
    async def broadcast_and_return(bot_message: str, response_data: dict):
        # Broadcast both user and bot messages to CRM
        from app.core.socket_manager import socket_manager
        await socket_manager.broadcast_event(
            "NEW_MESSAGE",
            {
                "session_id": str(active_session.visitor_uuid),
                "message": user_message,
                "sender": "user",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        await socket_manager.broadcast_event(
            "NEW_MESSAGE",
            {
                "session_id": str(active_session.visitor_uuid),
                "message": bot_message,
                "sender": "bot",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        )
        
        # If lead was updated, broadcast session update
        if active_session.lead_id:
            from app.api.live_chat import format_session_for_crm
            session_item = format_session_for_crm(active_session)
            await socket_manager.broadcast_event(
                "SESSION_UPDATED", 
                session_item
            )
        
        return response_data

    # Use the ChatbotService for consistent state management
    from app.services.chatbot import ChatbotService
    
    # Handle greetings first - with CTA
    if intent == IntentType.GREETING and not active_session.has_greeted:
        config = db.query(IntentConfig).filter(IntentConfig.intent_key == "GREETING").first()
        bot_msg = config.response_text if config else "Hello! Welcome to GTD Service! Are you interested in Import or Export?"
        active_session.has_greeted = True
        active_session.chat_state = ChatState.START
        db.commit()
        session_service.save_message(db, active_session, bot_msg, "bot")
        db.commit()
        
        # Return CTA response for greeting too
        return await broadcast_and_return(bot_msg, {
            "sessionId": str(active_session.visitor_uuid),
            "message": bot_msg,
            "state": active_session.chat_state,
            "type": ResponseType.CTA,
            "cta_label": "Book Demo",
            "action": "OPEN_LEAD_FORM",
            "conversation_status": active_session.conversation_mode,
            "server_time_utc": datetime.now(timezone.utc)
        })
    
    # Handle specialized intents with immediate CTA
    elif intent in [
        IntentType.REQUEST_DEMO, IntentType.LEAD_COLLECTION, IntentType.DEMO,
        IntentType.BUYER_SEARCH, IntentType.SUPPLIER_SEARCH, IntentType.HS_CODE_SEARCH,
        IntentType.COMPETITOR_ANALYSIS, IntentType.SHIPMENT_RECORDS, 
        IntentType.COUNTRY_TRADE_ANALYSIS, IntentType.PRODUCT_MARKET_RESEARCH,
        IntentType.PRICING_INQUIRY, IntentType.IMPORT_EXPORT
    ]:
        config = db.query(IntentConfig).filter(IntentConfig.intent_key == intent.value).first()
        if config and config.response_text:
            bot_msg = config.response_text
        else:
            bot_msg = "Great choice! To get detailed insights and personalized assistance, please Book a Demo with our experts."
        
        active_session.chat_state = ChatState.COMPLETE
        db.commit()
        session_service.save_message(db, active_session, bot_msg, "bot")
        db.commit()
        
        # Return CTA response for immediate lead form
        return await broadcast_and_return(bot_msg, {
            "sessionId": str(active_session.visitor_uuid),
            "message": bot_msg,
            "state": active_session.chat_state,
            "type": ResponseType.CTA,
            "cta_label": "Book Demo",
            "action": "OPEN_LEAD_FORM",
            "conversation_status": active_session.conversation_mode,
            "server_time_utc": datetime.now(timezone.utc)
        })
    
    # Use ChatbotService for the main conversation flow - with CTA
    else:
        try:
            chatbot_response = ChatbotService.handle_message(db, active_session, translated_message)
            bot_msg = chatbot_response.get("message", "")
            
            # Always return CTA response for ChatbotService responses too
            return await broadcast_and_return(bot_msg, {
                "sessionId": str(active_session.visitor_uuid),
                "message": bot_msg,
                "state": chatbot_response.get("state", active_session.chat_state),
                "type": ResponseType.CTA,
                "cta_label": chatbot_response.get("cta_label", "Book Demo"),
                "action": chatbot_response.get("action", "OPEN_LEAD_FORM"),
                "conversation_status": active_session.conversation_mode,
                "server_time_utc": datetime.now(timezone.utc)
            })
        except Exception as e:
            logger.error(f"ChatbotService error: {e}")
            bot_msg = "I'm here to help! Are you interested in Import or Export services?"
            session_service.save_message(db, active_session, bot_msg, "bot")
            db.commit()
            
            # Return CTA even for fallback messages
            return await broadcast_and_return(bot_msg, {
                "sessionId": str(active_session.visitor_uuid),
                "message": bot_msg,
                "state": active_session.chat_state,
                "type": ResponseType.CTA,
                "cta_label": "Book Demo",
                "action": "OPEN_LEAD_FORM",
                "conversation_status": active_session.conversation_mode,
                "server_time_utc": datetime.now(timezone.utc)
            })

    # This code should not be reached since all paths above return a response
    # But keeping as a safety fallback
    return {
        "sessionId": str(active_session.visitor_uuid),
        "message": "How can I assist you today?",
        "state": active_session.chat_state,
        "type": ResponseType.CTA,
        "cta_label": "Book Demo", 
        "action": "OPEN_LEAD_FORM",
        "conversation_status": active_session.conversation_mode,
        "server_time_utc": datetime.utcnow()
    }

# ── 3. Chat History (Persistence) ─────────────────────────────────────
@router.get("/history", response_model=List[ChatMessageResponse])
async def get_chat_history(request: Request, db: Session = Depends(get_db)):
    """
    Returns full message history for the current session to enable persistence.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)

    # Fallback: read session UUID from Authorization: Bearer <session_uuid>
    if not session_id:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            bearer_val = auth_header[len('Bearer '):].strip()
            if bearer_val and '.' not in bearer_val:
                session_id = bearer_val  # Use UUID directly

    if not session_id:
        return []

    active_session = session_service.get_active_session(db, session_id)
    if not active_session:
        return []

    if active_session.visitor_uuid and active_session.visitor_fingerprint:
        messages = (
            db.query(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.session_id)
            .filter(
                ChatSession.visitor_uuid == active_session.visitor_uuid,
                ChatSession.visitor_fingerprint == active_session.visitor_fingerprint,
                ChatSession.is_deleted == False
            )
            .order_by(ChatMessage.created_at_utc.desc())
            .limit(50)
            .all()
        )
        messages.reverse()
    else:
        messages = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == active_session.session_id)
            .order_by(ChatMessage.created_at_utc.asc())
            .all()
        )

    # Map database models to ChatMessageResponse schema
    history = []
    for m in messages:
        # Determine format based on structure (tuple from join vs direct instance)
        msg_obj = m[0] if isinstance(m, tuple) else m
        
        history.append({
            "sessionId": str(active_session.visitor_uuid),
            "message": msg_obj.message_text,
            "role": msg_obj.message_type, # Frontend expects 'role' for UI
            "state": active_session.chat_state, # Defaulting to current state
            "type": ResponseType.MESSAGE,
            "conversation_status": active_session.conversation_mode,
        })

    return history

# ── 4. Session Termination ────────────────────────────────────────────
@router.post("/session/end")
async def end_session(request: Request, response: Response, db: Session = Depends(get_db)):
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        session_service.close_session(db, session_id)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "success"}
