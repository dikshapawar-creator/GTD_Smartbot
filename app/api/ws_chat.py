"""
WebSocket Chat Endpoint — Real-time agent ↔ client communication.
Enterprise hardened:
- Tenant isolation for agents
- JWT validation with token version check
- Multi-party ownership verification
- Clean resource cleanup
"""
import logging
from datetime import datetime
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

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


def _get_db_session() -> DBSession:
    """Create a standalone DB session for WebSocket handlers."""
    return SessionLocal()


def _save_ws_message(
    db: DBSession, session_id: str, text: str, sender_type: str, tenant_id: int
):
    """Persist a WebSocket message to chat_messages with tenant/session scoping."""
    now_utc = datetime.utcnow()
    
    # We use session_id directly as it's a UUID, but we update the session last_activity
    msg = ChatMessage(
        session_id=session_id,
        message_type=sender_type,
        message_text=text,
        created_at_utc=now_utc,
        created_at_local=now_utc, # Fallback if local not available
    )
    db.add(msg)

    # Update session activity — scope by tenant_id for isolation safety
    chat_session = (
        db.query(ChatSession)
        .filter(
            ChatSession.session_id == session_id,
            ChatSession.tenant_id == tenant_id,
            ChatSession.is_deleted == False
        )
        .first()
    )
    if chat_session:
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
            chat_session = (
                db.query(ChatSession)
                .filter(
                    ChatSession.session_id == session_id, 
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

            # Verify session belongs to agent's tenant
            chat_session = (
                db.query(ChatSession)
                .filter(
                    ChatSession.session_id == session_id,
                    ChatSession.tenant_id == user_tenant_id, # ← TENANT ISOLATION
                    ChatSession.session_status == SessionStatus.ACTIVE,
                    ChatSession.is_deleted == False
                )
                .first()
            )
            if not chat_session:
                await websocket.close(code=4004, reason="Session not found in your tenant")
                return

            # Verify this agent is actually handling the session (if assigned)
            if chat_session.assigned_agent_id and chat_session.assigned_agent_id != agent_id:
                await websocket.close(code=4003, reason="Another agent is handling this session")
                return

            await manager.connect_agent(session_id, websocket)

            # Notify client and persist system message
            await manager.send_to_client(session_id, {
                "type": "system",
                "message": "A sales agent has joined the conversation.",
                "sender": "system",
            })
            _save_ws_message(
                db, session_id,
                "A sales agent has joined the conversation.",
                "system",
                user_tenant_id
            )

        else:
            await websocket.close(code=4000, reason="Invalid role specified")
            return

        # ── Message Loop ─────────────────────────────────────────────────
        while True:
            data = await websocket.receive_json()
            text = data.get("message", "").strip()
            if not text:
                continue

            if role == "client":
                _save_ws_message(db, session_id, text, "user", user_tenant_id)
                await manager.send_to_agent(session_id, {
                    "type": "message",
                    "message": text,
                    "sender": "user",
                })

            elif role == "agent":
                _save_ws_message(db, session_id, text, "agent", user_tenant_id)
                await manager.send_to_client(session_id, {
                    "type": "message",
                    "message": text,
                    "sender": "agent",
                })

    except WebSocketDisconnect:
        logger.info({"event": "ws_disconnect", "session_id": session_id, "role": role})
    except Exception as e:
        logger.error({"event": "ws_error", "session_id": session_id, "error": str(e)})
    finally:
        if role == "client":
            manager.disconnect_client(session_id)
        elif role == "agent":
            manager.disconnect_agent(session_id)
        db.close()
