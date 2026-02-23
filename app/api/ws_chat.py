"""
WebSocket Chat Endpoint — Real-time agent ↔ client communication.
Route: /ws/chat/{session_id}?role=client|agent&token=<jwt_or_session_id>
"""
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import jwt, JWTError
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.db.session import SessionLocal
from app.models.chat_session import ChatSession
from app.models.chat_message import ChatMessage
from app.models.auth import User
from app.services.websocket_manager import manager
from app.services.session_service import _now_utc, _to_local

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


def _get_db_session() -> DBSession:
    """Create a standalone DB session for WebSocket handlers."""
    return SessionLocal()


def _save_ws_message(
    db: DBSession, session_id: str, text: str, sender_type: str, tz: str = "UTC"
):
    """Persist a WebSocket message to chat_messages."""
    now_utc = _now_utc()
    now_local = _to_local(now_utc, tz)
    msg = ChatMessage(
        session_id=session_id,
        message_type=sender_type,
        message_text=text,
        created_at_utc=now_utc,
        created_at_local=now_local,
    )
    db.add(msg)

    # Update session activity
    chat_session = (
        db.query(ChatSession)
        .filter(ChatSession.session_id == session_id)
        .first()
    )
    if chat_session:
        chat_session.last_activity_utc = now_utc
        chat_session.total_messages += 1

    db.commit()


def _validate_agent_token(token: str) -> dict | None:
    """Decode JWT and return payload if valid agent."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return payload
    except JWTError:
        return None


@router.websocket("/ws/chat/{session_id}")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str,
    role: str = Query(...),
    token: str = Query(...),
):
    """
    Bidirectional WebSocket for live chat.

    - role=client, token=<session_id>  → client connection
    - role=agent,  token=<jwt>         → agent connection
    """
    db = _get_db_session()

    try:
        # ── Validate session exists ──────────────────────────────────────
        chat_session = (
            db.query(ChatSession)
            .filter(ChatSession.session_id == session_id, ChatSession.is_active == True)
            .first()
        )
        if not chat_session:
            await websocket.close(code=4004, reason="Session not found")
            return

        # ── Role-based authentication ────────────────────────────────────
        if role == "client":
            # Client must provide matching session_id as token
            if token != session_id:
                await websocket.close(code=4001, reason="Invalid client token")
                return
            await manager.connect_client(session_id, websocket)

        elif role == "agent":
            # Agent must provide valid JWT
            payload = _validate_agent_token(token)
            if not payload:
                await websocket.close(code=4001, reason="Invalid agent token")
                return

            # Verify agent exists and is active
            agent_id = int(payload["sub"])
            agent = db.query(User).filter(User.id == agent_id, User.is_active == True).first()
            if not agent:
                await websocket.close(code=4003, reason="Agent not found")
                return

            # Verify this agent is assigned to this session
            if chat_session.assigned_agent_id and chat_session.assigned_agent_id != agent_id:
                await websocket.close(code=4003, reason="Another agent owns this session")
                return

            await manager.connect_agent(session_id, websocket)

            # Notify client that agent connected
            await manager.send_to_client(session_id, {
                "type": "system",
                "message": "A sales agent has joined the conversation.",
                "sender": "system",
            })
            _save_ws_message(
                db, session_id,
                "A sales agent has joined the conversation.",
                "system",
                chat_session.timezone or "UTC",
            )

        else:
            await websocket.close(code=4000, reason="Invalid role")
            return

        # ── Message Loop ─────────────────────────────────────────────────
        while True:
            data = await websocket.receive_json()
            text = data.get("message", "").strip()
            if not text:
                continue

            tz = chat_session.timezone or "UTC"

            if role == "client":
                # Client → Agent
                _save_ws_message(db, session_id, text, "user", tz)
                await manager.send_to_agent(session_id, {
                    "type": "message",
                    "message": text,
                    "sender": "user",
                })

            elif role == "agent":
                # Agent → Client
                _save_ws_message(db, session_id, text, "agent", tz)
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
