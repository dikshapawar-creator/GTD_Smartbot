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
):
    """
    Global WebSocket for CRM dashboard updates (Intents, Leads, Users).
    SECURITY: Enforces tenant isolation via JWT.
    """
    await websocket.accept()
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
        except (JWTError, ValueError):
            await websocket.close(code=4001, reason="Invalid authentication token")
            return

        # Verify agent exists and is active
        agent = db.query(User).filter(User.id == agent_id).first()
        if not agent or not agent.is_active or agent.token_version != token_version:
            await websocket.close(code=4003, reason="Account restricted or session expired")
            return

        user_tenant_id = agent.tenant_id
        
        # Register with core socket manager for tenant broadcasts
        from app.core.socket_manager import socket_manager
        await socket_manager.connect(websocket, agent_id, user_tenant_id)
        
        logger.info(f"✅ [WS_CRM] Agent {agent_id} connected for tenant {user_tenant_id}")
        
        # Keepalive loop
        while True:
            data = await websocket.receive_text()
            try:
                parsed = json.loads(data)
                if parsed.get("type") == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "server_time_utc": datetime.now(timezone.utc).isoformat()
                    })
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        logger.info(f"ℹ️ [WS_CRM] Agent disconnected")
    except Exception as e:
        logger.error(f"❌ [WS_CRM] Global error: {e}")
    finally:
        if 'agent_id' in locals() and 'user_tenant_id' in locals():
            from app.core.socket_manager import socket_manager
            socket_manager.disconnect(websocket, agent_id, user_tenant_id)
        db.close()


def _get_db_session() -> DBSession:
    """Create a standalone DB session for WebSocket handlers."""
    return SessionLocal()


def _save_ws_message(
    db: DBSession, session_id: str, text: str, sender_type: str, tenant_id: int
):
    """Persist a WebSocket message to chat_messages with tenant/session scoping."""
    now_utc = datetime.now(timezone.utc)
    
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
        # We must use the REAL internal session_id for the FK constraint
        msg = ChatMessage(
            session_id=chat_session.session_id,
            message_type=sender_type,
            message_text=text,
            created_at_utc=now_utc,
            created_at_local=now_utc, # Fallback if local not available
        )
        db.add(msg)

        chat_session.last_activity_utc = now_utc
        chat_session.total_messages += 1

    db.commit()


@router.websocket("/ws/chat/{session_id}")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str,
    role: str = Query(...),
    token: str = Query(...),
):
    """
    Bidirectional WebSocket for live chat.
    SECURITY: Enforces tenant isolation and role-gated access.
    """
    await websocket.accept()
    db = _get_db_session()
    user_tenant_id = None

    try:
        # ── Role-based authentication ────────────────────────────────────
        if role == "client":
            # Client must provide matching session_id as token
            if token != session_id:
                await websocket.close(code=4001, reason="Invalid client token")
                return
            
            # Fetch session to get tenant_id for later message persists
            # Fetch session to get tenant_id for later message persists
            chat_session = (
                db.query(ChatSession)
                .filter(
                    (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id), 
                    ChatSession.session_status == SessionStatus.ACTIVE, 
                    ChatSession.is_deleted == False
                )
                .first()
            )
            if not chat_session:
                await websocket.close(code=4004, reason="Session not found or inactive")
                return
            
            user_tenant_id = chat_session.tenant_id
            await manager.connect_client(session_id, websocket)
            
            # ⏰ INACTIVITY: Start monitor on connection
            asyncio.create_task(send_inactivity_message(session_id, chat_session.last_activity_utc))

        elif role == "agent":
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

            user_tenant_id = agent.tenant_id

            # Verify session belongs to agent's tenant (allow CLOSED sessions to be reactivated)
            # Fetch session to get tenant_id for later message persists
            chat_session = (
                db.query(ChatSession)
                .filter(
                    (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id),
                    ChatSession.tenant_id == user_tenant_id, # ← TENANT ISOLATION
                    ChatSession.is_deleted == False
                )
                .first()
            )
            if not chat_session:
                await websocket.close(code=4004, reason="Session not found in your tenant")
                return

            # Reactivate session if closed
            if chat_session.session_status == SessionStatus.CLOSED:
                 chat_session.session_status = SessionStatus.ACTIVE
                 chat_session.status = "ACTIVE"

            # Sync bot-stop flag
            chat_session.agent_joined = True
            db.commit()

            # Verify this agent is actually handling the session (if assigned)
            if chat_session.assigned_agent_id and chat_session.assigned_agent_id != agent_id:
                await websocket.close(code=4003, reason="Another agent is handling this session")
                return

            # Register with both managers
            await manager.connect_agent(session_id, websocket)
            from app.core.socket_manager import socket_manager
            await socket_manager.connect(websocket, agent_id, user_tenant_id)

        else:
            await websocket.close(code=4000, reason="Invalid role specified")
            return

        # ── Message Loop ─────────────────────────────────────────────────
        logger.info(f"➡️ [WS] Entered persistent loop for session {session_id} ({role})")
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
                if not text:
                    continue

                if role == "client":
                    # 🔥 PERSISTENCE: Save user message
                    _save_ws_message(db, session_id, text, "user", user_tenant_id)
                    
                    # ⏰ INACTIVITY: Monitor
                    asyncio.create_task(send_inactivity_message(session_id, datetime.now(timezone.utc)))
                    
                    # 🔥 Broadcast to CRM Dashboard
                    from app.core.socket_manager import socket_manager
                    await socket_manager.broadcast_event(
                        "NEW_MESSAGE",
                        {
                            "session_id": session_id,
                            "message": text,
                            "sender": "user",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        },
                        tenant_id=user_tenant_id  # ← Isolated
                    )

                    # ✅ ALWAYS re-fetch session mode from DB to avoid stale cache
                    db.expire_all()
                    # Fetch session to get tenant_id for later message persists
                    fresh_session = db.query(ChatSession).filter(
                        (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id)
                    ).first()

                    if fresh_session and fresh_session.conversation_mode == ConversationMode.HUMAN:
                        logger.info(f"Relaying client message to agent for session {session_id}")
                        await manager.send_to_agent(session_id, {
                            "type": "message",
                            "message": text,
                            "sender": "user",
                        })
                    else:
                        # Bot is handling
                        try:
                            from app.services.chatbot import ChatbotService
                            bot_response = ChatbotService.handle_message(
                                db=db,
                                chat_session=fresh_session,
                                user_message=text
                            )
                            reply_text = bot_response.get("message", "")
                            if reply_text:
                                await websocket.send_json({
                                    "type": "message",
                                    "message": reply_text,
                                    "sender": "bot",
                                    "state": bot_response.get("state"),
                                    "type_hint": bot_response.get("type"),
                                    "cta_label": bot_response.get("cta_label"),
                                    "action": bot_response.get("action"),
                                })
                        except Exception as bot_err:
                            logger.error(f"Bot response error for session {session_id}: {bot_err}")

                elif role == "agent":
                    _save_ws_message(db, session_id, text, "agent", user_tenant_id)
                    
                    # 🔥 Broadcast to CRM Dashboard
                    from app.core.socket_manager import socket_manager
                    await socket_manager.broadcast_event(
                        "NEW_MESSAGE",
                        {
                            "session_id": session_id,
                            "message": text,
                            "sender": "agent",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        },
                        tenant_id=user_tenant_id  # ← Isolated
                    )

                    # 🔧 ENHANCED LOGGING: Debug message routing
                    logger.info(f"[WS_AGENT] Attempting to send message to client for session: {session_id}")
                    logger.info(f"[WS_AGENT] Available clients: {list(manager._clients.keys())}")
                    
                    normalized_sid = session_id.lower()
                    if manager.has_client(normalized_sid):
                        logger.info(f"[WS_AGENT] Client found for session {normalized_sid}, sending message")
                        await manager.send_to_client(normalized_sid, {
                            "type": "message",
                            "message": text,
                            "sender": "agent",
                        })
                    else:
                        logger.warning(f"[WS_AGENT] No client connected for session {normalized_sid}. Available clients: {list(manager._clients.keys())}")

            except (RuntimeError, ValueError) as e:
                # Catch potential socket protocol errors without breaking the loop
                logger.error(f"⚠️ [WS] Non-fatal loop error for {session_id}: {e}")
                continue

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
