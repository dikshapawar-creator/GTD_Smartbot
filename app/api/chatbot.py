import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

from app.core.dependencies import get_db
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode

from app.models.chat_message import ChatMessage
from app.models.blocked import BlockedVisitor

logger = logging.getLogger(__name__)
from app.services.chatbot import ChatbotService
from app.services import session_service, intent_service, greeting_handler, lead_service
from app.core import utils
from app.models.lead import Lead, LeadStatus
from app.models.intent_config import IntentConfig
from app.schemas.chatbot import (
    ChatMessageRequest, ChatMessageResponse, 
    ResponseType, SessionInitResponse, SessionInitRequest, ChatState
)

router = APIRouter(prefix="/chat", tags=["Chatbot"])

# ── 1. Session Initialization ──────────────────────────────────────────
@router.post("/session/init", response_model=SessionInitResponse)
async def initialize_session(request: Request, response: Response, background_tasks: BackgroundTasks, init_req: Optional[SessionInitRequest] = None, db: Session = Depends(get_db)):
    """
    Initializes or restores a chatbot session.
    """
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    
    if session_id:
        active_session = session_service.get_active_session(db, session_id, request.state.tenant_id)
        # Verify session is truly active and exists
        if active_session and active_session.session_status == SessionStatus.ACTIVE:
            return {
                "session_token": str(active_session.visitor_uuid),
                "message": "Welcome back to Smart Chatbot! How can I assist with your trade operations and intelligence needs today?",
                "state": str(active_session.chat_state or "START").replace("ChatState.", "").replace("CHATSTATE.", "").upper() if active_session.chat_state != "GREETING" else "START",
                "type": ResponseType.CTA,
                "ctas": [
                    {"label": "Book Demo", "action": "OPEN_LEAD_FORM", "icon": "🚀"},
                    {"label": "Connect with Data Expert", "action": "HANDOFF", "icon": "💬", "type": "secondary"}
                ],
                "conversation_status": active_session.conversation_mode,
                "server_time_utc": datetime.now(timezone.utc)
            }

    # Extract client info for new session
    client_ip = utils.get_client_ip(request)
    meta = utils.get_visitor_metadata(request)
    fingerprint = utils.generate_visitor_fingerprint(client_ip, meta["user_agent"])

    # 🚨 SECURITY: Blocked Visitor Check
    is_blocked = db.query(BlockedVisitor).filter(
        (BlockedVisitor.ip_address == client_ip) | 
        (BlockedVisitor.visitor_fingerprint == fingerprint),
        BlockedVisitor.tenant_id == request.state.tenant_id  # ← Isolated
    ).first()
    
    if is_blocked:
        logger.warning(f"Blocked visitor attempt: IP={client_ip}, FP={fingerprint}")
        # We don't want to give too much away, just a generic error or silent ignore
        return {
            "session_token": None,
            "message": "Access restricted. Please contact support if you believe this is an error.",
            "conversation_status": "CLOSED"
        }
    
    # if is_blocked:
    #     logger.warning(
    #         f"Blocked access attempt from client_ip: {client_ip} | fingerprint: {fingerprint} "
    #         f"| reason: {is_blocked.reason}"
    #     )
    #     raise HTTPException(
    #         status_code=403, 
    #         detail="Your access has been restricted due to security policy violations."
    #     )

    # Geo-location is moved to background task to avoid blocking the init request
    country, city, timezone_str = "Unknown", "Unknown", "UTC"

    visitor_uuid_ext = init_req.visitor_uuid if init_req else None
    
    # Check if returning visitor with an ACTIVE session
    existing_session = None
    is_returning = False
    carry_over_lead_id = None
    
    if visitor_uuid_ext:
        logger.info(f"[SESSION_INIT] Looking for existing session for visitor_uuid: {visitor_uuid_ext}")
        
        # 🔥 ENTERPRISE: Consolidate any duplicate sessions first
        from app.api.live_chat import consolidate_visitor_sessions
        existing_session = consolidate_visitor_sessions(db, visitor_uuid_ext, request.state.tenant_id)
        
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
            ChatSession.tenant_id == request.state.tenant_id,
            ChatSession.is_deleted == False
            ).order_by(ChatSession.started_at_utc.desc()).first()
            
            if prior_session:
                is_returning = True
                logger.info(f"[SESSION_INIT] Found prior session history for visitor {visitor_uuid_ext}")
                # Check for lead id in any of their past sessions
                session_with_lead = db.query(ChatSession).filter(
                ChatSession.visitor_uuid == visitor_uuid_ext,
                ChatSession.lead_id.isnot(None),
                ChatSession.tenant_id == request.state.tenant_id,
                ChatSession.is_deleted == False
                ).order_by(ChatSession.started_at_utc.desc()).first()
                
                if session_with_lead:
                    carry_over_lead_id = session_with_lead.lead_id
                    logger.info(f"[SESSION_INIT] Returning visitor {visitor_uuid_ext} has previous lead_id {carry_over_lead_id}")
    else:
        logger.warning("[SESSION_INIT] No visitor_uuid provided in session initialization request")

    if not existing_session:
        # 🔥 SENIOR FIX: Strictly use resolved tenant_id from middleware
        current_tenant_id = request.state.tenant_id
        if not current_tenant_id:
            logger.error(f"Chat session init failed: No tenant identified for request from {client_ip}")
            raise HTTPException(status_code=403, detail="Tenant context required.")

        logger.info(f"[SESSION_INIT] Creating NEW session for visitor {visitor_uuid_ext} on tenant {current_tenant_id}")
        
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
            tenant_id=current_tenant_id,

            visitor_uuid=visitor_uuid_ext,
            lead_id=carry_over_lead_id # 🔥 Identity Retention
        )
        logger.info(f"[SESSION_INIT] NEW session created: {new_session.session_id} for tenant {current_tenant_id}")
    
    # 🚨 COMMIT BEFORE BROADCAST
    db.commit()

    # 🔥 Immediately broadcast to CRM
    from app.core.socket_manager import socket_manager
    from app.api.live_chat import format_session_for_crm
    
    session_item = format_session_for_crm(new_session)
    await socket_manager.broadcast_event(
        "NEW_CONVERSATION", 
        session_item,
        tenant_id=new_session.tenant_id  # ← Isolated
    )

    # Fetch professional greeting from DB for consistency
    if is_returning:
        greeting_res = {"message": "Welcome back 👋 How can I help with your trade operations today?"}
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

    result_resp = {
        "session_token": str(new_session.visitor_uuid),
        "message": greeting_res["message"],
        "state": ChatState.START.value,
        "type": ResponseType.CTA,
        "ctas": [
            {"label": "Book Demo", "action": "OPEN_LEAD_FORM", "icon": "🚀"},
            {"label": "Connect with Data Expert", "action": "HANDOFF", "icon": "💬", "type": "secondary"}
        ],
        "conversation_status": new_session.conversation_mode,
        "server_time_utc": datetime.now(timezone.utc)
    }

    # ⏰ INACTIVITY: Monitor for 60s after first greeting
    background_tasks.add_task(send_inactivity_message, str(new_session.visitor_uuid), new_session.last_activity_utc)
    
    # 🌍 BACKGROUND GEO LOOKUP
    if not existing_session and client_ip and client_ip not in ("127.0.0.1", "::1", ""):
        from app.services.geo_service import lookup_ip_geo
        
        def bg_geo_update(session_id: str, ip: str):
            with SessionLocal() as bg_db:
                try:
                    c, ct, tz = lookup_ip_geo(ip)
                    if c != "Unknown" or ct != "Unknown":
                        sess = bg_db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
                        if sess:
                            sess.country = c
                            sess.city = ct
                            sess.timezone = tz
                            bg_db.commit()
                except Exception as e:
                    logger.error(f"Background geo lookup failed: {e}")
                    
        background_tasks.add_task(bg_geo_update, new_session.session_id, client_ip)
    
    return result_resp


# ── 1. AGENT & SESSION GATES ──────────────────────────────────────────
from app.services.inactivity_service import send_inactivity_message

@router.post("/message", response_model=ChatMessageResponse)
async def send_message(request: Request, msg_req: ChatMessageRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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
        active_session = session_service.get_active_session(db, session_id, request.state.tenant_id)
        if not active_session:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")
    except ValueError as e:
        # Handle invalid UUID format
        logger.error(f"Invalid session UUID format: {session_id}, error: {e}")
        raise HTTPException(status_code=401, detail="Invalid session format.")

    # A. Reactivate CLOSED session if it's in BOT mode
    if active_session.session_status == SessionStatus.CLOSED:
        is_bot_mode = (
            active_session.conversation_mode == ConversationMode.BOT and
            active_session.current_mode == ConversationMode.BOT and
            not active_session.agent_joined and
            active_session.assigned_agent_id is None
        )
        if is_bot_mode:
            logger.info(f"Re-activating closed session {active_session.session_id} for bot response (REST)")
            active_session.session_status = SessionStatus.ACTIVE
            active_session.is_active = True
            db.commit()

    # B. Check for Agent activity or Handoff state (Silence Rule)
    is_agent_active = (
        active_session.agent_joined or 
        active_session.assigned_agent_id is not None or 
        active_session.is_locked or
        active_session.chat_state == ChatState.HANDOFF_SENT.value or
        active_session.conversation_mode == ConversationMode.HUMAN or
        active_session.current_mode == ConversationMode.HUMAN
    )

    if not is_agent_active and active_session.conversation_mode != ConversationMode.BOT:
        # Fallback check for last message from agent (Staleness: 30 minutes)
        from datetime import timedelta
        stale_cutoff = datetime.utcnow() - timedelta(minutes=30)
        recent_agent_msg = db.query(ChatMessage).filter(
            ChatMessage.session_id == active_session.session_id,
            ChatMessage.message_type == "agent",
            ChatMessage.created_at_utc >= stale_cutoff
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
            },
            tenant_id=active_session.tenant_id  # ← Isolated
        )

        return {
            "sessionId": str(active_session.visitor_uuid),
            "message": "", 
            "type": ResponseType.MESSAGE,
            "state": str(active_session.chat_state or "START").replace("ChatState.", "").replace("CHATSTATE.", "").upper() if active_session.chat_state != "GREETING" else "START",
            "conversation_status": active_session.conversation_mode,
            "server_time_utc": datetime.now(timezone.utc)
        }

    # B. Re-activate session if it was CLOSED but receiving new message in BOT mode
    if active_session.session_status == SessionStatus.CLOSED:
        active_session.session_status = SessionStatus.ACTIVE
        db.flush() # Sync but no commit yet
        logger.info(f"Re-activated closed session {active_session.session_id} for REST bot response")

    # ── 2. INTENT & LEAD LOGIC ──────────────────────────────────────────
    user_message = msg_req.message
    
    # ✅ PERSISTENCE: Save user message early (No commit yet)
    session_service.save_message(db, active_session, user_message, "user", commit=False)

    # ⏰ INACTIVITY: Monitor for 60s
    background_tasks.add_task(send_inactivity_message, str(active_session.visitor_uuid), active_session.last_activity_utc)
    
    # Analytics: Spam Detection
    from app.services.spam_service import check_message_spam
    if check_message_spam(db, active_session, user_message):
        active_session.spam_flag = True
        active_session.session_status = SessionStatus.CLOSED
        db.commit() # Block immediate
        return {
            "sessionId": str(active_session.visitor_uuid),
            "message": "Security policy violation detected. Session closed.",
            "state": str(active_session.chat_state or "START").replace("ChatState.", "").replace("CHATSTATE.", "").upper() if active_session.chat_state != "GREETING" else "START",
            "conversation_status": active_session.conversation_mode,
            "server_time_utc": datetime.now(timezone.utc)
        }

    # Analytics: Language Translation
    from app.services.language_service import detect_and_translate
    lang_code, translated_message = detect_and_translate(user_message)
    if not active_session.language or active_session.language == "en":
        active_session.language = lang_code
        db.flush()

    # Analytics: Lead Scoring (Evaluate translated message)
    from app.services.scoring_service import update_session_score
    active_session = update_session_score(db, active_session, translated_message)
    
    if active_session.lead_status == "Hot":
        # Placeholder for smart sales alert
        print(f"🔥 HOT LEAD DETECTED: Session {active_session.session_id}")

    intent_key = intent_service.detect_intent(db, translated_message, active_session.tenant_id)
    current_state = active_session.chat_state
    bot_msg = ""
    
    # Check for Human/Representative request first (Priority 1)
    if intent_key == "HANDOFF":
        # Dynamic response for handoff
        from app.services.chatbot import ChatbotService
        bot_msg = ChatbotService._get_dynamic_response(
            db,
            "HANDOFF",
            "Thank you. We will arrange a call for you shortly.\n\nYou can discuss all your questions with our team during the meeting.\n\nRegarding your data and requirements, our team will provide you with the appropriate solution.",
            active_session.tenant_id
        )
        active_session.chat_state = ChatState.HANDOFF_SENT.value
        session_service.save_message(db, active_session, bot_msg, "bot", commit=False)
        db.commit() # FINAL COMMIT FOR HANDOFF
        
        #  Broadcast handoff signal
        from app.core.socket_manager import socket_manager
        await socket_manager.broadcast_event(
            "NEW_MESSAGE",
            {
                "session_id": str(active_session.visitor_uuid),
                "message": user_message,
                "sender": "user",
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            tenant_id=active_session.tenant_id  # ← Isolated
        )
        await socket_manager.broadcast_event(
            "NEW_MESSAGE",
            {
                "session_id": str(active_session.visitor_uuid),
                "message": bot_msg,
                "sender": "bot",
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            tenant_id=active_session.tenant_id  # ← Isolated
        )
        
        return {
            "sessionId": str(active_session.visitor_uuid),
            "message": bot_msg,
            "state": str(active_session.chat_state or "START").replace("ChatState.", "").replace("CHATSTATE.", "").upper() if active_session.chat_state != "GREETING" else "START",
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
                "message_type": "user",
                "purpose": "crm_updates",  # ← CRITICAL: Use crm_updates purpose
                "timestamp": datetime.utcnow().isoformat(),
                "msg_id": f"rest_user_{datetime.utcnow().timestamp()}",
                "created_at_ist": datetime.now(timezone.utc).strftime('%d %b, %I:%M %p')
            },
            tenant_id=active_session.tenant_id
        )
        await socket_manager.broadcast_event(
            "NEW_MESSAGE",
            {
                "session_id": str(active_session.visitor_uuid),
                "message": bot_message,
                "sender": "bot",
                "message_type": "bot",
                "purpose": "crm_updates",  # ← CRITICAL: Use crm_updates purpose
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "msg_id": f"rest_bot_{datetime.now(timezone.utc).timestamp()}",
                "created_at_ist": datetime.now(timezone.utc).strftime('%d %b, %I:%M %p')
            },
            tenant_id=active_session.tenant_id
        )
        
        # If lead was updated, broadcast session update
        if active_session.lead_id:
            from app.api.live_chat import format_session_for_crm
            session_item = format_session_for_crm(active_session)
            await socket_manager.broadcast_event(
                "SESSION_UPDATED", 
                session_item,
                tenant_id=active_session.tenant_id  # ← Isolated
            )
        
        return response_data

    # Use the ChatbotService for centralized intent and state management
    from app.services.chatbot import ChatbotService
    
    try:
        chatbot_response = ChatbotService.handle_message(db, active_session, translated_message, commit=False)
        bot_msg = chatbot_response.get("message", "")
        
        # FINAL DATABASE COMMIT after all processing
        db.commit()

        # Determine Response Type (CTA or MESSAGE)
        res_type = ResponseType.CTA if chatbot_response.get("type") == "CTA" else ResponseType.MESSAGE
        
        # ⏰ INACTIVITY MONITOR: Reset timer on every message
        from app.services.inactivity_service import send_inactivity_message
        background_tasks.add_task(send_inactivity_message, str(active_session.visitor_uuid), active_session.last_activity_utc)

        return await broadcast_and_return(bot_msg, {
            "sessionId": str(active_session.visitor_uuid),
            "message": bot_msg,
            "state": str(chatbot_response.get("state") or active_session.chat_state or "START").replace("ChatState.", "").replace("CHATSTATE.", "").upper() if (chatbot_response.get("state") or active_session.chat_state) != "GREETING" else "START",
            "type": res_type,
            "cta_label": chatbot_response.get("cta_label") if res_type == ResponseType.CTA else None,
            "action": chatbot_response.get("action") if res_type == ResponseType.CTA else None,
            "intent": chatbot_response.get("intent"),
            "conversation_status": active_session.conversation_mode,
            "server_time_utc": datetime.now(timezone.utc)
        })
    except Exception as e:
        logger.error(f"ChatbotService error: {e}", exc_info=True)
        from app.services.chatbot import ChatbotService
        bot_msg = ChatbotService._get_dynamic_response(
            db, 
            "WELCOME_QUESTION", 
            "I'm here to help! Are you interested in Import or Export services?",
            active_session.tenant_id
        )
        session_service.save_message(db, active_session, bot_msg, "bot", commit=False)
        db.commit()
        
        # Return CTA even for fallback messages
        return await broadcast_and_return(bot_msg, {
            "sessionId": str(active_session.visitor_uuid),
            "message": bot_msg,
            "state": str(active_session.chat_state or "START").replace("ChatState.", "").replace("CHATSTATE.", "").upper() if active_session.chat_state != "GREETING" else "START",
            "type": ResponseType.CTA,
            "ctas": [{"label": "Book Demo", "action": "OPEN_LEAD_FORM", "icon": "🚀", "type": "primary"}],
            "conversation_status": active_session.conversation_mode,
            "server_time_utc": datetime.now(timezone.utc)
        })

    # This code should not be reached since all paths above return a response
    # But keeping as a safety fallback
    return {
        "sessionId": str(active_session.visitor_uuid),
        "message": "How can I assist you today?",
        "state": str(active_session.chat_state or "START").replace("ChatState.", "").replace("CHATSTATE.", "").upper() if active_session.chat_state != "GREETING" else "START",
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

    active_session = session_service.get_active_session(db, session_id, request.state.tenant_id)
    if not active_session:
        return []

    if active_session.visitor_uuid and active_session.visitor_fingerprint:
        messages = (
            db.query(ChatMessage)
            .join(ChatSession, ChatMessage.session_id == ChatSession.session_id)
            .filter(
                ChatSession.visitor_uuid == active_session.visitor_uuid,
                ChatSession.visitor_fingerprint == active_session.visitor_fingerprint,
                ChatSession.tenant_id == active_session.tenant_id,
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
        
        # Determine response metadata
        m_type = ResponseType.MESSAGE
        m_role = msg_obj.message_type
        
        if msg_obj.message_type == 'form':
            m_type = ResponseType.FORM
            m_role = 'bot' # Show as bot in UI
        
        history.append({
            "sessionId": str(active_session.visitor_uuid),
            "message": msg_obj.message_text,
            "role": m_role,
            "state": str(active_session.chat_state or "START").replace("ChatState.", "").replace("CHATSTATE.", "").upper() if active_session.chat_state != "GREETING" else "START",
            "type": m_type,
            "conversation_status": active_session.conversation_mode,
            "created_at_ist": msg_obj.created_at_ist if hasattr(msg_obj, 'created_at_ist') else None,
            "is_read": bool(getattr(msg_obj, 'is_read', False)),
            "read_at": msg_obj.read_at.isoformat() if getattr(msg_obj, 'read_at', None) else None,
        })

    return history

# ── 4. Session Termination ────────────────────────────────────────────
@router.post("/session/end")
async def end_session(request: Request, response: Response, db: Session = Depends(get_db)):
    session_id = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_id:
        session_service.close_session(db, session_id, request.state.tenant_id)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
    return {"status": "success"}


