"""
WebSocket Chat Endpoint — Real-time agent ↔ client communication.
Enterprise hardened:
- Tenant isolation for agents
- JWT validation with token version check
- Multi-party ownership verification
- Clean resource cleanup
"""
import logging
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import jwt, JWTError
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.db.session import SessionLocal
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode
from app.models.chat_message import ChatMessage
from app.models.auth import User
from app.services.websocket_manager import manager
from app.services.inactivity_service import send_inactivity_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live-chat", tags=["WebSocket"])
legacy_router = APIRouter(tags=["Legacy WebSocket"]) # No prefix


@router.websocket("/ws/crm/updates")
async def websocket_crm_updates(
    websocket: WebSocket,
    token: str = Query(...),
    tenant_id: Optional[int] = Query(None),
):
    """
    Global WebSocket for CRM dashboard updates (Intents, Leads, Users).
    SECURITY: Enforces tenant isolation via JWT.
    """
    logger.info(f"🔌 WebSocket CRM connection attempt from {websocket.client}")
    
    try:
        await websocket.accept()
        logger.info("✅ WebSocket accepted")
    except Exception as e:
        logger.error(f"❌ Failed to accept WebSocket: {e}")
        return
    
    db = _get_db_session()
    
    try:
        # ── Secure JWT Validation ──
        try:
            payload = jwt.decode(
                token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
            )
            agent_id = int(payload.get("sub"))
            token_version = payload.get("token_version")
            if not agent_id or token_version is None:
                raise JWTError()
            logger.info(f"🔑 JWT validated for agent {agent_id}")
        except (JWTError, ValueError) as e:
            logger.error(f"❌ JWT validation failed: {e}")
            await websocket.close(code=4001, reason="Invalid authentication token")
            return

        # Verify agent exists and is active
        agent = db.query(User).filter(User.id == agent_id).first()
        if not agent or not agent.is_active or agent.token_version != token_version:
            logger.error(f"❌ Agent validation failed: agent={agent}, active={agent.is_active if agent else None}, token_version_match={agent.token_version == token_version if agent else None}")
            await websocket.close(code=4003, reason="Account restricted or session expired")
            return

        user_tenant_id = agent.tenant_id
        if tenant_id:
            if agent.is_super_admin:
                user_tenant_id = tenant_id
            else:
                from app.models.auth import UserTenant
                has_access = db.query(UserTenant).filter(
                    UserTenant.user_id == agent.id, 
                    UserTenant.tenant_id == tenant_id, 
                    UserTenant.status == True
                ).first()
                if has_access:
                    user_tenant_id = tenant_id
                else:
                    logger.error(f"❌ Tenant access denied: agent={agent_id}, tenant={tenant_id}")
                    await websocket.close(code=4003, reason="Access denied for this workspace")
                    return
        
        # Register with core socket manager for tenant broadcasts
        from app.core.socket_manager import socket_manager
        await socket_manager.connect(websocket, agent_id, user_tenant_id)
        
        logger.info(f"✅ [WS_CRM] Agent {agent_id} connected for tenant {user_tenant_id}")
        
        # Keepalive loop
        while True:
            try:
                data = await websocket.receive_text()
                try:
                    parsed = json.loads(data)
                    if parsed.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "server_time_utc": datetime.now(timezone.utc).isoformat()
                        })
                        logger.debug(f"🏓 Pong sent to agent {agent_id}")
                except json.JSONDecodeError:
                    logger.warning(f"📩 Non-JSON data received: {data[:100]}")
            except WebSocketDisconnect:
                logger.info(f"🔌 Agent {agent_id} disconnected normally")
                break
            except Exception as e:
                logger.error(f"❌ Error in message loop: {e}")
                break

    except WebSocketDisconnect:
        logger.info(f"ℹ️ [WS_CRM] Agent disconnected")
    except Exception as e:
        logger.error(f"❌ [WS_CRM] Global error: {e}", exc_info=True)
    finally:
        if 'agent_id' in locals() and 'user_tenant_id' in locals():
            from app.core.socket_manager import socket_manager
            socket_manager.disconnect(websocket, agent_id, user_tenant_id)
            logger.info(f"🔌 Agent {agent_id} disconnected and cleaned up")
        db.close()


def _get_db_session() -> DBSession:
    """Create a standalone DB session for WebSocket handlers."""
    return SessionLocal()


def _save_ws_message(
    db: DBSession, 
    session_id: str, 
    text: str, 
    sender_type: str, 
    tenant_id: int,
    sender_user_id: Optional[int] = None,
    sender_name: Optional[str] = None,
    sender_email: Optional[str] = None
) -> Optional[ChatMessage]:
    """Persist a WebSocket message to chat_messages with tenant/session scoping."""
    now_utc = datetime.now(timezone.utc)
    
    # Fix potential UTF-16 encoding issues before processing
    if text and '\x00' in text:
        original_text = text
        text = text.replace('\x00', '')
        logger.warning(f"Fixed UTF-16 encoding in _save_ws_message for session {session_id}: {len(original_text)} -> {len(text)} chars")
    
    # Update session activity — scope by tenant_id for isolation safety
    chat_session = (
        db.query(ChatSession)
        .filter(
            (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id),
            ChatSession.tenant_id == tenant_id,
            ChatSession.is_deleted == False
        )
        .first()
    )
    
    if chat_session:
        # --- DEDUPLICATION LOGIC ---
        from datetime import timedelta
        stale_cutoff = now_utc - timedelta(seconds=3)
        duplicate = (
            db.query(ChatMessage)
            .filter(
                ChatMessage.session_id == chat_session.session_id,
                ChatMessage.message_type == sender_type,
                ChatMessage.message_text == text,
                ChatMessage.created_at_utc >= stale_cutoff
            )
            .first()
        )
        if duplicate:
            logger.info(f"Duplicate WS message ignored: [{sender_type}] {text[:50]}{'...' if len(text) > 50 else ''}")
            return None
        # ---------------------------

        # We must use the REAL internal session_id for the FK constraint
        msg = ChatMessage(
            tenant_id=chat_session.tenant_id,
            session_id=chat_session.session_id,
            message_type=sender_type,
            message_text=text,
            created_at=now_utc,
            created_at_utc=now_utc,
            created_at_local=now_utc, # Fallback if local not available
            sender_user_id=sender_user_id,
            sender_name=sender_name,
            sender_email=sender_email
        )
        db.add(msg)

        chat_session.last_activity_utc = now_utc
        chat_session.total_messages += 1
        
        db.commit()
        db.refresh(msg)
        return msg

    return None


@router.websocket("/ws/chat/{session_id}")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str,
    role: str = Query(...),
    token: str = Query(...),
    tenant_id: Optional[int] = Query(None),
):
    """
    Bidirectional WebSocket for live chat.
    SECURITY: Enforces tenant isolation and role-gated access.
    """
    logger.info(f"🔌 WebSocket connection attempt: session_id={session_id}, role={role}, tenant_id={tenant_id}")
    
    try:
        await websocket.accept()
        logger.info(f"✅ WebSocket accepted for session {session_id} ({role})")
    except Exception as e:
        logger.error(f"❌ Failed to accept WebSocket for session {session_id}: {e}")
        return
    
    db = _get_db_session()
    user_tenant_id = None

    try:
        # ── Role-based authentication ────────────────────────────────────
        if role == "client":
            logger.info(f"🔵 [WS_CLIENT] Client WebSocket connection attempt: session_id={session_id}")
            # Client must provide matching session_id as token
            if token != session_id:
                logger.error(f"❌ [WS_CLIENT] Token mismatch: token={token}, session_id={session_id}")
                await websocket.close(code=4001, reason="Invalid client token")
                return
            
            # Fetch session to get tenant_id for later message persists
            # Be permissive with session status to allow client connections, but prefer active sessions
            chat_session = (
                db.query(ChatSession)
                .filter(
                    (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id),
                    ChatSession.is_deleted == False
                )
                .order_by(
                    # Use CASE statement for SQL Server compatibility
                    ChatSession.last_activity_at.desc()
                )
                .first()
            )
            
            if not chat_session:
                logger.error(f"❌ [WS_CLIENT] Session {session_id} not found or inactive")
                # Try to find the session with any status to debug
                any_session = db.query(ChatSession).filter(
                    (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id),
                    ChatSession.is_deleted == False
                ).first()
                if any_session:
                    logger.info(f"🔍 [WS_CLIENT] Found session with status: {any_session.session_status}, mode: {any_session.current_mode}")
                else:
                    logger.error(f"🔍 [WS_CLIENT] No session found at all for {session_id}")
                await websocket.close(code=4004, reason="Session not found or inactive")
                return
            
            user_tenant_id = chat_session.tenant_id
            logger.info(f"✅ [WS_CLIENT] About to register client for session {session_id} (tenant: {user_tenant_id})")
            await manager.connect_client(session_id, websocket)
            logger.info(f"✅ [WS_CLIENT] Client successfully registered for session {session_id}")
            
            # Verify registration
            logger.info(f"🔍 [WS_CLIENT] Post-registration check: has_client={manager.has_client(session_id)}")
            logger.info(f"🔍 [WS_CLIENT] All registered clients: {list(manager._clients.keys())}")
            
            # ⏰ INACTIVITY: Start monitor on connection
            asyncio.create_task(send_inactivity_message(session_id, chat_session.last_activity_utc))

        elif role == "agent":
            logger.info(f"🔑 Agent WebSocket connection attempt: session_id={session_id}, tenant_id={tenant_id}")
            # ── Secure JWT Validation for Agent ──
            try:
                payload = jwt.decode(
                    token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
                )
                agent_id = int(payload.get("sub"))
                token_version = payload.get("token_version")
                if not agent_id or token_version is None:
                    raise JWTError()
            except (JWTError, ValueError):
                await websocket.close(code=4001, reason="Invalid authentication token")
                return

            # Verify agent exists, is active, and token version matches
            agent = db.query(User).filter(User.id == agent_id).first()
            if not agent or not agent.is_active or agent.token_version != token_version:
                await websocket.close(code=4003, reason="Account restricted or session expired")
                return

            # 🏢 Determine Tenant Context
            user_tenant_id = agent.tenant_id
            if tenant_id:
                if agent.is_super_admin:
                    user_tenant_id = tenant_id
                else:
                    from app.models.auth import UserTenant
                    has_access = db.query(UserTenant).filter(
                        UserTenant.user_id == agent.id,
                        UserTenant.tenant_id == tenant_id,
                        UserTenant.status == True
                    ).first()
                    if has_access:
                        user_tenant_id = tenant_id
                    else:
                        await websocket.close(code=4003, reason="Access denied for this workspace")
                        return

            # Verify session exists and determine correct tenant context
            logger.info(f"🔍 Looking for session {session_id} in tenant {user_tenant_id}")
            logger.info(f"🔍 Agent details: id={agent_id}, tenant_id={agent.tenant_id}, is_super_admin={agent.is_super_admin}")
            
            # CRITICAL FIX: Find the most recent session that can be activated (not just active ones)
            # Allow agents to connect to CLOSED sessions to reopen them
            chat_session = (
                db.query(ChatSession)
                .filter(
                    (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id),
                    ChatSession.is_deleted == False,
                    ChatSession.session_status.in_(['active', 'ACTIVE', 'closed', 'CLOSED', 'bot', 'BOT'])  # Allow reactivation
                )
                .order_by(ChatSession.last_activity_at.desc())  # Most recent first
                .first()
            )
            
            if chat_session:
                logger.info(f"✅ Session found: session_id={chat_session.session_id}, visitor_uuid={chat_session.visitor_uuid}, tenant_id={chat_session.tenant_id}, status={chat_session.session_status}")
                
                # CRITICAL FIX: Reactivate closed sessions when agent connects
                if chat_session.session_status in ['closed', 'CLOSED']:
                    logger.info(f"🔄 Reactivating closed session {session_id}")
                    chat_session.session_status = SessionStatus.ACTIVE
                    chat_session.is_locked = True
                    chat_session.agent_joined = True
                    chat_session.last_activity_at = datetime.now(timezone.utc)
                    chat_session.last_activity_utc = datetime.now(timezone.utc)
                    db.commit()
                    logger.info(f"✅ Session {session_id} reactivated successfully")
            else:
                logger.error(f"❌ No active session found for {session_id}")
                # Try to find any session with similar UUID to debug
                any_session = db.query(ChatSession).filter(
                    (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id),
                    ChatSession.is_deleted == False
                ).order_by(ChatSession.last_activity_at.desc()).first()
                if any_session:
                    logger.info(f"🔍 Found session with status: {any_session.session_status}, mode: {any_session.current_mode}")
                    # If it's a closed session, suggest reactivation
                    if any_session.session_status in ['closed', 'CLOSED']:
                        logger.info(f"💡 Session {session_id} is closed but can be reactivated by agent connection")
                else:
                    logger.error(f"🔍 No session found at all for {session_id}")
            
            if not chat_session:
                logger.error(f"❌ Session {session_id} not found in any tenant")
                await websocket.close(code=4004, reason="Session not found")
                return
            
            # CRITICAL FIX: For super admin, always allow access to any tenant's session
            if chat_session.tenant_id != user_tenant_id:
                if agent.is_super_admin:
                    logger.info(f"🔑 Super admin {agent_id} accessing session {session_id} in tenant {chat_session.tenant_id} (agent's context: {user_tenant_id})")
                    user_tenant_id = chat_session.tenant_id  # Update tenant context to match session
                else:
                    logger.error(f"❌ Session {session_id} found in tenant {chat_session.tenant_id}, but agent is in tenant {user_tenant_id}")
                    await websocket.close(code=4004, reason=f"Session found in tenant {chat_session.tenant_id}, but you're in tenant {user_tenant_id}")
                    return

            # Update agent attribution if not already set
            if not chat_session.assigned_agent_id:
                chat_session.assigned_agent_id = agent_id
                chat_session.assigned_agent_email = agent.email
                chat_session.assigned_agent_name = agent.full_name
                chat_session.agent_name = agent.full_name # Legacy support
                chat_session.assigned_at = datetime.now(timezone.utc)
                chat_session.agent_joined_at = datetime.now(timezone.utc)

            # Sync bot-stop flag and mode
            chat_session.agent_joined = True
            chat_session.conversation_mode = ConversationMode.HUMAN
            chat_session.status = "HUMAN"
            db.commit()

            # Verify this agent is actually handling the session (if assigned)
            if chat_session.assigned_agent_id and chat_session.assigned_agent_id != agent_id:
                # Allow super admin to take over any session
                if not agent.is_super_admin:
                    await websocket.close(code=4003, reason="Another agent is handling this session")
                    return
                else:
                    # Super admin can take over - update assignment
                    logger.info(f"🔑 Super admin {agent_id} taking over session from agent {chat_session.assigned_agent_id}")
                    chat_session.assigned_agent_id = agent_id
                    chat_session.assigned_agent_email = agent.email
                    chat_session.assigned_agent_name = agent.full_name
                    chat_session.agent_name = agent.full_name
                    db.commit()

            # Register with both managers
            await manager.connect_agent(session_id, websocket)
            from app.core.socket_manager import socket_manager
            await socket_manager.connect(websocket, agent_id, user_tenant_id)
            logger.info(f"✅ [WS_AGENT] Successfully registered agent {agent_id} for session {session_id} in tenant {user_tenant_id}")
            
            # Verify registration
            logger.info(f"🔍 [WS_AGENT] Post-registration check: has_agent={manager.has_agent(session_id)}")
            logger.info(f"🔍 [WS_AGENT] All registered agents: {list(manager._agents.keys())}")

        else:
            await websocket.close(code=4000, reason="Invalid role specified")
            return

        # ── Message Loop ─────────────────────────────────────────────────
        logger.info(f"➡️ [WS] Entered persistent loop for session {session_id} ({role}) - agent_id: {agent_id if role == 'agent' else 'N/A'}, tenant: {user_tenant_id}")
        
        # Send initial connection confirmation
        try:
            await websocket.send_json({
                "type": "connection_established",
                "session_id": session_id,
                "role": role,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            logger.info(f"✅ [WS] Sent connection confirmation for {session_id} ({role})")
        except Exception as e:
            logger.error(f"❌ [WS] Failed to send connection confirmation: {e}")
            return
        
        while True:
            try:
                # Use receive_text and parse manually for better error visibility
                raw_data = await websocket.receive_text()
                
                try:
                    data = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(f"📩 [WS] Received non-JSON data from {role}: {raw_data[:100]}")
                    continue

                msg_type = data.get("type", "message")
                logger.debug(f"📩 [WS] Received {msg_type} from {role}")

                # ── Handle Typing Indicator ──────────────────────────────
                if msg_type == "typing":
                    is_typing = data.get("is_typing", False)
                    if role == "client":
                        await manager.send_to_agent(session_id, {
                            "type": "TYPING_EVENT",
                            "is_typing": is_typing,
                            "sender": "user",
                            "session_id": session_id,
                        })
                    else:
                        await manager.send_to_client(session_id, {
                            "type": "TYPING_EVENT",
                            "is_typing": is_typing,
                            "sender": "agent",
                            "session_id": session_id,
                        })
                    continue

                # ── Handle Ping/Pong ─────────────────────────────────────
                if msg_type == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "server_time_utc": datetime.now(timezone.utc).isoformat()
                    })
                    continue

                text = data.get("message", "").strip()
                
                # Fix potential UTF-16 encoding issues
                if text and '\x00' in text:
                    text = text.replace('\x00', '')
                    logger.warning(f"Fixed UTF-16 encoding in WebSocket message for session {session_id}")
                
                if not text:
                    continue

                if role == "client":
                    # 🔥 PERSISTENCE: Save user message
                    _save_ws_message(db, session_id, text, "user", user_tenant_id)
                    
                    # ⏰ INACTIVITY: Monitor
                    asyncio.create_task(send_inactivity_message(session_id, datetime.now(timezone.utc)))
                    
                    # 🔥 Broadcast user message to CRM Dashboard
                    from app.core.socket_manager import socket_manager
                    await socket_manager.broadcast_event(
                        "NEW_MESSAGE",
                        {
                            "session_id": session_id,
                            "message": text,
                            "sender": "user",
                            "message_type": "user",
                            "purpose": "crm_updates",  # ← CRITICAL: Use crm_updates purpose
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "msg_id": f"ws_user_{datetime.now(timezone.utc).timestamp()}",
                            "created_at_ist": datetime.now(timezone.utc).strftime('%d %b, %I:%M %p')
                        },
                        tenant_id=user_tenant_id
                    )

                    # ✅ ALWAYS re-fetch session mode from DB to avoid stale cache
                    db.expire_all()
                    # Fetch session to get tenant_id for later message persists
                    fresh_session = db.query(ChatSession).filter(
                        (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id)
                    ).first()

                    # 🚨 AGENT SILENCE RULE: If mode is explicitly BOT, bot takes over.
                    # Otherwise, check for agent activity/assignment.
                    is_human_mode = False
                    if fresh_session:
                        if fresh_session.conversation_mode == ConversationMode.BOT:
                             is_human_mode = False
                        else:
                            is_human_mode = (
                                fresh_session.conversation_mode == ConversationMode.HUMAN or
                                fresh_session.current_mode == ConversationMode.HUMAN or
                                fresh_session.agent_joined or
                                fresh_session.is_locked or
                                fresh_session.assigned_agent_id is not None
                            )

                    if is_human_mode:
                        logger.info(f"Relaying client message to agent for session {session_id} (HUMAN MODE)")
                        await manager.send_to_agent(session_id, {
                            "type": "message",
                            "message": text,
                            "sender": "user",
                            "session_id": session_id,
                        })
                    else:
                        # Re-activate session if it was CLOSED but receiving new message in BOT mode
                        if fresh_session and fresh_session.session_status == SessionStatus.CLOSED:
                            fresh_session.session_status = SessionStatus.ACTIVE
                            db.commit()
                            logger.info(f"Re-activated closed session {session_id} for bot response")

                        # Bot is handling - process bot response
                        try:
                            from app.services.chatbot import ChatbotService
                            bot_response = ChatbotService.handle_message(
                                db=db,
                                chat_session=fresh_session,
                                user_message=text
                            )
                            reply_text = bot_response.get("message", "")
                            
                            # ⚡ CRITICAL: Fix potential UTF-16 encoding issues (null bytes)
                            # This prevents character-by-character streaming on some environments.
                            if isinstance(reply_text, str) and ('\x00' in reply_text or '\u0000' in reply_text):
                                reply_text = reply_text.replace('\x00', '').replace('\u0000', '')
                                logger.warning(f"Fixed UTF-16 encoding in bot response for session {session_id}")
                            
                            if reply_text:
                                # ⚡ IMPORTANT: ChatbotService.handle_message ALREADY saves the message to DB.
                                # To avoid "Duplicate WS message ignored" logs and double-persisting, 
                                # we should only use _save_ws_message if we need the msg_id and it wasn't saved.
                                # But actually, handle_message is the source of truth now.
                                
                                # Fetch the last bot message for this session to get the ID if needed
                                from app.models.chat_message import ChatMessage
                                bot_msg = db.query(ChatMessage).filter(
                                    ChatMessage.session_id == session_id,
                                    ChatMessage.message_type == "bot"
                                ).order_by(ChatMessage.id.desc()).first()
                                
                                # 🔵 Send to Visitor Widget
                                # Ensure we send a valid JSON with a clean string
                                await websocket.send_json({
                                    "type": "message",
                                    "message": str(reply_text), 
                                    "sender": "bot",
                                    "purpose": "chatbot",
                                    "state": bot_response.get("state"),
                                    "type_hint": bot_response.get("type"),
                                    "cta_label": bot_response.get("cta_label"),
                                    "action": bot_response.get("action"),
                                    "msg_id": bot_msg.id if bot_msg else None,
                                })

                                # 🔥 Broadcast bot message to CRM Dashboard
                                from app.core.socket_manager import socket_manager
                                await socket_manager.broadcast_event(
                                    "NEW_MESSAGE",
                                    {
                                        "session_id": session_id,
                                        "message": str(reply_text),
                                        "sender": "bot",
                                        "message_type": "bot",
                                        "purpose": "crm_updates",
                                        "timestamp": datetime.now(timezone.utc).isoformat(),
                                        "msg_id": bot_msg.id if bot_msg else f"ws_bot_{datetime.now(timezone.utc).timestamp()}",
                                        "message_status": "sent",
                                        "created_at_ist": datetime.now(timezone.utc).strftime('%d %b, %I:%M %p')
                                    },
                                    tenant_id=user_tenant_id
                                )
                                logger.info(f"🔥 Bot message broadcast to CRM for session {session_id}")
                        except Exception as bot_err:
                            logger.error(f"Bot response error for session {session_id}: {bot_err}")

                elif role == "agent":
                    # Save agent message
                    saved_msg = _save_ws_message(
                        db, session_id, text, "agent", user_tenant_id,
                        sender_user_id=agent_id,
                        sender_name=agent.full_name,
                        sender_email=agent.email
                    )
                    
                    # 🔥 Broadcast agent message to CRM Dashboard
                    from app.core.socket_manager import socket_manager
                    await socket_manager.broadcast_event(
                        "NEW_MESSAGE",
                        {
                            "session_id": session_id,
                            "message": text,
                            "sender": "agent",
                            "message_type": "agent",
                            "sender_name": agent.full_name,
                            "sender_email": agent.email,
                            "purpose": "crm_updates",  # ← CRITICAL: Use crm_updates purpose
                            "msg_id": data.get("client_msg_id") or f"ws_agent_{datetime.now(timezone.utc).timestamp()}",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "message_status": "sent",
                            "created_at_ist": datetime.now(timezone.utc).strftime('%d %b, %I:%M %p')
                        },
                        tenant_id=user_tenant_id
                    )

                    # 🔧 ENHANCED LOGGING: Debug message routing
                    logger.info(f"[WS_AGENT] Attempting to send message to client for session: {session_id}")
                    logger.info(f"[WS_AGENT] Message text: {text[:50]}...")
                    logger.info(f"[WS_AGENT] Available clients: {list(manager._clients.keys())}")
                    logger.info(f"[WS_AGENT] Available agents: {list(manager._agents.keys())}")
                    
                    # Send message to client using improved manager
                    try:
                        await manager.send_to_client(session_id, {
                            "type": "message",
                            "message": text,
                            "sender": "agent",
                            "purpose": "chatbot",  # ← Required for Chatbot Widget routing
                            "msg_id": saved_msg.id if saved_msg else None,
                            "message_status": "delivered",
                            "session_id": session_id,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        logger.info(f"✅ [WS_AGENT] Message successfully sent to client for session {session_id}")
                        
                        # Update message status to delivered
                        if saved_msg:
                            # Broadcast delivery status to CRM
                            await socket_manager.broadcast_event(
                                "MESSAGE_STATUS_UPDATE",
                                {
                                    "msg_id": saved_msg.id,
                                    "session_id": session_id,
                                    "status": "delivered",
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                },
                                tenant_id=user_tenant_id
                            )
                    except Exception as send_error:
                        logger.error(f"❌ [WS_AGENT] Failed to send message to client: {send_error}")
                        
                        # Save the message anyway so it appears in chat history
                        if saved_msg:
                            logger.info(f"[WS_AGENT] Message saved to database with ID: {saved_msg.id}")
                        
                        # The message will be visible when client refreshes or reconnects
                        logger.info(f"[WS_AGENT] Message will be available via REST API when client reconnects")

                # ── Handle Message Read Receipt ──────────────────────────
                elif msg_type == "message_read":
                    msg_id = data.get("msg_id")
                    if msg_id and role == "client":
                        # Mark message as read
                        message = db.query(ChatMessage).filter(
                            ChatMessage.id == msg_id,
                            ChatMessage.session_id.in_(
                                db.query(ChatSession.session_id).filter(
                                    (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id)
                                )
                            )
                        ).first()
                        
                        if message and not message.is_read:
                            message.is_read = True
                            message.read_at = datetime.now(timezone.utc)
                            db.commit()
                            
                            # Broadcast read status to CRM
                            from app.core.socket_manager import socket_manager
                            await socket_manager.broadcast_event(
                                "MESSAGE_STATUS_UPDATE",
                                {
                                    "msg_id": msg_id,
                                    "session_id": session_id,
                                    "status": "read",
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                },
                                tenant_id=user_tenant_id
                            )
                    continue

            except WebSocketDisconnect as e:
                # WebSocket disconnected - this should break the loop
                logger.info(f"🔴 [WS] WebSocket disconnected in loop for {session_id}: {e}")
                break
            except (RuntimeError, ValueError) as e:
                # Catch closed socket state errors to break the loop safely
                logger.error(f"⚠️ [WS] Fatal socket state error for {session_id}: {e}")
                break
            except Exception as e:
                # Log other exceptions but don't break the loop
                logger.error(f"⚠️ [WS] Non-fatal error in message loop for {session_id}: {e}", exc_info=True)
                # Continue the loop instead of breaking

    except WebSocketDisconnect:
        logger.info(f"🔴 [WS] Client disconnected: {session_id} ({role})")
    except Exception as e:
        logger.error(f"❌ [WS] Global error for {session_id}: {e}", exc_info=True)
    finally:
        if role == "client":
            manager.disconnect_client(session_id)
        elif role == "agent":
            manager.disconnect_agent(session_id)
            try:
                from app.core.socket_manager import socket_manager
                # Note: agent_id might not be in scope if authentication failed early, 
                # but it's okay because we handle that in the auth block.
                # Here we'll use a safer disconnect if possible or just rely on local cleanup.
                if 'agent_id' in locals():
                    socket_manager.disconnect(websocket, agent_id, user_tenant_id)
            except Exception:
                pass

        db.close()


# ── Legacy WebSocket Catch-all ───────────────────────────────────────
@legacy_router.websocket("/ws/chat/{session_id}")
async def legacy_chat_websocket(
    websocket: WebSocket, 
    session_id: str,
    role: Optional[str] = Query(None),
    token: Optional[str] = Query(None)
):
    """
    Handles old WebSocket paths (/ws/chat/...) by redirecting to the main handler.
    This fixes the issue where reverse proxy strips /live-chat prefix.
    """
    logger.info(f"Legacy WS path accessed: session={session_id}, role={role}")
    
    # Redirect to the main WebSocket handler
    await websocket_chat(websocket, session_id, role or "client", token or session_id)
