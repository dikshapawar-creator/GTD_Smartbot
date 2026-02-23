"""
Live Chat REST API — CRM endpoints for agent takeover management.
Authenticated with JWT (requires sales role or above).
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.core.dependencies import get_db
from app.api.deps import get_current_user
from app.models.auth import User
from app.models.chat_session import ChatSession
from app.models.chat_message import ChatMessage
from app.models.lead import Lead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live-chat", tags=["Live Chat"])


# ── Response Schemas ────────────────────────────────────────────────────

class LiveConversationItem(BaseModel):
    session_id: str
    status: str
    assigned_agent_id: Optional[int] = None
    is_locked: bool
    lead_name: Optional[str] = None
    lead_company: Optional[str] = None
    lead_email: Optional[str] = None
    last_activity_utc: Optional[datetime] = None
    total_messages: int = 0
    started_at_utc: Optional[datetime] = None

    class Config:
        from_attributes = True


class ChatMessageItem(BaseModel):
    id: int
    session_id: str
    message_type: str  # user | bot | agent | system
    message_text: str
    created_at_utc: datetime

    class Config:
        from_attributes = True


# ── List Active Conversations ───────────────────────────────────────────

@router.get("/conversations", response_model=List[LiveConversationItem])
def list_live_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all sessions awaiting agent or currently connected."""
    sessions = (
        db.query(ChatSession)
        .filter(
            ChatSession.is_active == True,
            or_(
                ChatSession.status == "waiting_for_agent",
                ChatSession.status == "human",
            ),
        )
        .order_by(ChatSession.last_activity_utc.desc())
        .all()
    )

    results = []
    for s in sessions:
        # Try to find associated lead (by session_id or recent lead by IP)
        lead = db.query(Lead).filter(Lead.id == s.session_id).first()
        results.append(
            LiveConversationItem(
                session_id=s.session_id,
                status=s.status,
                assigned_agent_id=s.assigned_agent_id,
                is_locked=s.is_locked,
                lead_name=lead.name if lead else None,
                lead_company=lead.company if lead else None,
                lead_email=lead.email if lead else None,
                last_activity_utc=s.last_activity_utc,
                total_messages=s.total_messages,
                started_at_utc=s.started_at_utc,
            )
        )

    return results


# ── Connect Agent to Conversation ───────────────────────────────────────

@router.post("/connect/{session_id}")
def connect_to_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Agent claims a waiting conversation. Enforces single-agent lock."""
    chat_session = (
        db.query(ChatSession)
        .filter(ChatSession.session_id == session_id, ChatSession.is_active == True)
        .first()
    )
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Lock mechanism — prevent multiple agents
    if chat_session.is_locked and chat_session.assigned_agent_id != current_user.id:
        raise HTTPException(
            status_code=409,
            detail="This conversation is already being handled by another agent.",
        )

    # Update session state
    chat_session.status = "human"
    chat_session.assigned_agent_id = current_user.id
    chat_session.is_locked = True
    db.commit()

    logger.info({
        "event": "agent_connected",
        "session_id": session_id,
        "agent_id": current_user.id,
    })

    return {
        "success": True,
        "message": "Connected to conversation.",
        "session_id": session_id,
        "agent_id": current_user.id,
    }


# ── Close Conversation ──────────────────────────────────────────────────

@router.post("/close/{session_id}")
def close_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Agent closes a live conversation."""
    chat_session = (
        db.query(ChatSession)
        .filter(ChatSession.session_id == session_id, ChatSession.is_active == True)
        .first()
    )
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Only the assigned agent or an admin can close
    if (
        chat_session.assigned_agent_id
        and chat_session.assigned_agent_id != current_user.id
        and current_user.role.level < 2
    ):
        raise HTTPException(status_code=403, detail="Not authorized to close this conversation.")

    chat_session.status = "closed"
    chat_session.is_locked = False
    db.commit()

    logger.info({
        "event": "conversation_closed",
        "session_id": session_id,
        "closed_by": current_user.id,
    })

    return {"success": True, "message": "Conversation closed."}


# ── Get Message History ─────────────────────────────────────────────────

@router.get("/messages/{session_id}", response_model=List[ChatMessageItem])
def get_conversation_messages(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve full message history for a session."""
    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at_utc.asc())
        .all()
    )
    return messages
