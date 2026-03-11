"""
Live Chat REST API — CRM endpoints for agent takeover management.
Enterprise hardened:
- Tenant isolation on every query
- Role-based access control (min level 1 = sales / agent)
- Paginated history and message retrieval
- Secure WebSocket with JWT validation
- Atomic intervention with BackgroundTasks for broadcasts
"""
import logging
from typing import List, Optional, Dict
from datetime import datetime, timedelta, timezone as dt_timezone

from fastapi import (
    APIRouter, Depends, HTTPException, BackgroundTasks,
    Query, WebSocket, WebSocketDisconnect, status as http_status
)
from jose import jwt, JWTError
from pydantic import BaseModel
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db
from app.api.deps import get_current_user, require_role
from app.models.auth import User
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode
from app.models.chat_message import ChatMessage
from app.models.lead import Lead
from app.models.blocked import BlockedVisitor
from app.core.socket_manager import socket_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live-chat", tags=["Live Chat"])

def is_valid_uuid(val: str) -> bool:
    """Helper to check if a string is a valid UUID before querying UNIQUEIDENTIFIER columns."""
    import uuid
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False


# ── Response Schemas ────────────────────────────────────────────────────

class LiveConversationItem(BaseModel):
    session_id: str
    session_uuid: str
    session_status: str
    current_mode: str
    agent_name: Optional[str] = None
    message_count: int = 0
    previous_session_count: int = 0
    repeat_visitor: bool = False
    created_at: Optional[datetime] = None
    last_message_at: Optional[datetime] = None
    is_locked: bool = False
    lead_name: Optional[str] = None
    lead_company: Optional[str] = None
    # Senior IP & Metadata
    initial_ip: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    browser: Optional[str] = None
    os: Optional[str] = None
    device_type: Optional[str] = None
    lead_score: Optional[int] = 0
    lead_status: Optional[str] = "Cold"
    spam_flag: bool = False
    language: Optional[str] = "en"
    duration_seconds: Optional[int] = 0
    started_at_local: Optional[datetime] = None

    class Config:
        from_attributes = True


class ConversationDetailItem(LiveConversationItem):
    """Extended schema with PII — only returned by detail endpoint."""
    lead_email: Optional[str] = None
    lead_phone: Optional[str] = None


class ChatMessageItem(BaseModel):
    id: int
    session_id: str
    message_type: str  # user | bot | agent | system
    message_text: str
    created_at_utc: datetime

    class Config:
        from_attributes = True


class PaginatedHistory(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[LiveConversationItem]


class PaginatedMessages(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[ChatMessageItem]


class LeadUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None


# ── Internal Helper — Paginated Conversation Query ──────────────────────

def _build_conversation_query(
    db: Session,
    tenant_id: int,
    only_active: bool,
    status_filter: Optional[str],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
):
    """
    Builds a base query with full tenant isolation and optional filters.
    Never returns deleted sessions.
    """
    q = (
        db.query(ChatSession, User.full_name.label("agent_name"))
        .outerjoin(User, ChatSession.assigned_agent_id == User.id)
        .filter(
            ChatSession.tenant_id == tenant_id,          # ← TENANT ISOLATION
            ChatSession.is_deleted == False,              # ← SOFT DELETE GUARD
        )
    )
    if only_active:
        q = q.filter(ChatSession.is_active == True)      # ← DASHBOARD VISIBILITY ONLY

    if only_active:
        # Filter for ACTIVE sessions that have had activity within the expiry window
        expiry_limit = datetime.now(dt_timezone.utc).replace(tzinfo=None) - timedelta(minutes=settings.SESSION_EXPIRY_MINUTES)
        q = q.filter(
            ChatSession.session_status == SessionStatus.ACTIVE,
            ChatSession.last_activity_utc >= expiry_limit
        )
    elif status_filter and status_filter.upper() in ("ACTIVE", "CLOSED"):
        q = q.filter(ChatSession.session_status == status_filter.upper())

    if date_from:
        q = q.filter(ChatSession.last_activity_utc >= date_from)
    if date_to:
        q = q.filter(ChatSession.last_activity_utc <= date_to)

    return q.order_by(ChatSession.started_at_utc.desc())


def _assemble_items(sessions, db: Session) -> List[LiveConversationItem]:
    """
    Assembles LiveConversationItem list from session rows using bulk lookups
    to avoid N+1 queries.
    """
    if not sessions:
        return []

    lead_ids = [row[0].lead_id for row in sessions if row[0].lead_id]

    # Bulk-fetch leads
    lead_map: Dict[str, Lead] = {}
    if lead_ids:
        leads = db.query(Lead).filter(Lead.id.in_(lead_ids)).all()
        lead_map = {str(l.id): l for l in leads}

    # Bulk-fetch history counts by lead
    history_by_lead: Dict[str, int] = {}
    if lead_ids:
        counts = (
            db.query(ChatSession.lead_id, func.count(ChatSession.id))
            .filter(ChatSession.lead_id.in_(lead_ids), ChatSession.is_deleted == False)
            .group_by(ChatSession.lead_id)
            .all()
        )
        history_by_lead = {lid: max(0, count - 1) for lid, count in counts}

    # Bulk-fetch history counts by fingerprint (Senior repeat check)
    history_by_fingerprint: Dict[str, int] = {}
    fingerprints = [s[0].visitor_fingerprint for s in sessions if s[0].visitor_fingerprint]
    if fingerprints:
        counts = (
            db.query(ChatSession.visitor_fingerprint, func.count(ChatSession.id))
            .filter(ChatSession.visitor_fingerprint.in_(fingerprints), ChatSession.is_deleted == False)
            .group_by(ChatSession.visitor_fingerprint)
            .all()
        )
        history_by_fingerprint = {fp: max(0, count - 1) for fp, count in counts}

    results = []
    for row in sessions:
        s = row[0]
        agent_name = row[1]
        lead = lead_map.get(str(s.lead_id)) if s.lead_id else None

        past_count = 0
        if s.lead_id:
            past_count = history_by_lead.get(s.lead_id, 0)
        elif s.visitor_fingerprint:
            past_count = history_by_fingerprint.get(s.visitor_fingerprint, 0)

        results.append(
            LiveConversationItem.model_validate(
                {
                    "session_id": s.session_id,
                    "session_uuid": str(s.session_uuid),
                    "session_status": s.session_status,
                    "current_mode": s.conversation_mode,
                    "agent_name": agent_name,
                    "message_count": s.total_messages,
                    "previous_session_count": past_count,
                    "repeat_visitor": past_count > 0,
                    "created_at": s.started_at_utc.replace(tzinfo=dt_timezone.utc) if s.started_at_utc else None,
                    "last_message_at": s.last_activity_utc.replace(tzinfo=dt_timezone.utc) if s.last_activity_utc else None,
                    "is_locked": s.is_locked,
                    "lead_name": lead.name if lead else (f"{s.initial_ip} ({s.country})" if s.initial_ip and s.country else "Visitor"),
                    "lead_company": lead.company if lead else None,
                    "initial_ip": s.initial_ip,
                    "country": s.country,
                    "city": s.city,
                    "browser": s.browser,
                    "os": s.os,
                    "device_type": s.device_type,
                    "lead_score": s.lead_score,
                    "lead_status": s.lead_status,
                    "spam_flag": s.spam_flag,
                    "language": s.language,
                    "duration_seconds": s.duration_seconds,
                    "started_at_local": s.started_at_local.replace(tzinfo=dt_timezone.utc) if s.started_at_local else None, # Even local is stored naive, treat as UTC for transport
                }
            )
        )

    return results


# ── List Active Conversations (Live View) ───────────────────────────────

@router.get("/conversations", response_model=List[LiveConversationItem])
def list_live_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),  # Min: sales/agent
):
    """
    List all sessions (BOT + HUMAN, ACTIVE + CLOSED) for the current tenant.
    Agents can see every chatbot conversation in one view.
    """
    q = _build_conversation_query(
        db, current_user.tenant_id, only_active=True,
        status_filter=None, date_from=None, date_to=None
    )
    sessions = q.all()
    return _assemble_items(sessions, db)


# ── Conversation Analytics ──────────────────────────────────────────────

@router.get("/analytics")
def get_conversation_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
):
    """
    Real-time session analytics for the dashboard.
    """
    tenant_id = current_user.tenant_id
    
    active_sessions = db.query(func.count(ChatSession.id)).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.session_status == SessionStatus.ACTIVE,
        ChatSession.is_deleted == False
    ).scalar()
    
    avg_duration = db.query(func.avg(ChatSession.duration_seconds)).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.is_deleted == False,
        ChatSession.duration_seconds.isnot(None)
    ).scalar() or 0
    
    avg_score = db.query(func.avg(ChatSession.lead_score)).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.is_deleted == False
    ).scalar() or 0
    
    spam_sessions = db.query(func.count(ChatSession.id)).filter(
        ChatSession.tenant_id == tenant_id,
        ChatSession.spam_flag == True,
        ChatSession.is_deleted == False
    ).scalar()
    
    return {
        "active_visitors": active_sessions,
        "avg_lead_score": round(float(avg_score or 0), 1),
        "avg_duration": round(float(avg_duration or 0), 0),
        "spam_visitors": spam_sessions,
        "agent_chats": active_sessions # Placeholder for active agent handling
    }


# ── Paginated History (Archive View) ────────────────────────────────────

@router.get("/history", response_model=PaginatedHistory)
def list_conversation_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=25, ge=1, le=100, description="Max 100 per page"),
    status_filter: Optional[str] = Query(default=None, description="ACTIVE | CLOSED"),
    date_from: Optional[datetime] = Query(default=None, description="ISO datetime lower bound"),
    date_to: Optional[datetime] = Query(default=None, description="ISO datetime upper bound"),
):
    """
    Paginated archive of ALL sessions (ACTIVE + CLOSED) for the current tenant.
    Supports optional status and date-range filtering.
    """
    q = _build_conversation_query(
        db, current_user.tenant_id, only_active=False,
        status_filter=status_filter, date_from=date_from, date_to=date_to
    )

    total = q.count()
    offset = (page - 1) * page_size
    sessions = q.offset(offset).limit(page_size).all()

    return PaginatedHistory(
        total=total,
        page=page,
        page_size=page_size,
        items=_assemble_items(sessions, db),
    )


# ── Conversation Detail (with PII) ──────────────────────────────────────

@router.get("/detail/{session_id}", response_model=ConversationDetailItem)
def get_conversation_detail(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
):
    """
    Returns full detail for a single session including lead_email.
    Enforces tenant isolation — 404 if session belongs to another tenant.
    """
    query_id = session_id
    id_filter = ChatSession.session_id == query_id
    if is_valid_uuid(query_id):
        id_filter = (ChatSession.session_uuid == query_id) | (ChatSession.session_id == query_id)

    row = (
        db.query(ChatSession, User.full_name.label("agent_name"))
        .outerjoin(User, ChatSession.assigned_agent_id == User.id)
        .filter(
            id_filter,
            ChatSession.tenant_id == current_user.tenant_id,
            ChatSession.is_deleted == False,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    s, agent_name = row
    lead = db.query(Lead).filter(Lead.id == s.lead_id).first() if s.lead_id else None

    return ConversationDetailItem.model_validate(
        {
            "session_id": s.session_id,
            "session_uuid": str(s.session_uuid),
            "session_status": s.session_status,
            "current_mode": s.conversation_mode,
            "agent_name": agent_name,
            "message_count": s.total_messages,
            "previous_session_count": 0,
            "repeat_visitor": False,
            "created_at": s.started_at_utc.replace(tzinfo=dt_timezone.utc) if s.started_at_utc else None,
            "last_message_at": s.last_activity_utc.replace(tzinfo=dt_timezone.utc) if s.last_activity_utc else None,
            "is_locked": s.is_locked,
            "lead_name": lead.name if lead else "Visitor",
            "lead_company": lead.company if lead else None,
            "lead_email": lead.email if lead else None,
            "lead_phone": lead.phone if lead else None,
            "initial_ip": s.initial_ip,
            "country": s.country,
            "city": s.city,
            "browser": s.browser,
            "os": s.os,
            "device_type": s.device_type,
            "lead_score": s.lead_score,
            "lead_status": s.lead_status,
            "spam_flag": s.spam_flag,
            "language": s.language,
            "duration_seconds": s.duration_seconds,
            "started_at_local": s.started_at_local.replace(tzinfo=dt_timezone.utc) if s.started_at_local else None,
        }
    )


# ── Paginated Messages ──────────────────────────────────────────────────

@router.get("/messages/{session_id}", response_model=PaginatedMessages)
def get_conversation_messages(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """
    Paginated message retrieval for a session.
    SECURITY: Verifies session belongs to the current user's tenant before
    returning any messages. Prevents cross-tenant message leakage.
    """
    # ── Ownership / Tenant Check ───────────────────────────────────────
    query_id = session_id
    id_filter = ChatSession.session_id == query_id
    if is_valid_uuid(query_id):
        id_filter = (ChatSession.session_uuid == query_id) | (ChatSession.session_id == query_id)

    session_exists = (
        db.query(ChatSession.session_id)
        .filter(
            id_filter,
            ChatSession.tenant_id == current_user.tenant_id,  # ← CRITICAL
            ChatSession.is_deleted == False,
        )
        .first()
    )
    if not session_exists:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    internal_session_id = session_exists[0]

    # ── Paginated Query ───────────────────────────────────────────────
    q = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == internal_session_id)
        .order_by(ChatMessage.created_at_utc.asc())
    )
    total = q.count()
    offset = (page - 1) * page_size
    messages = q.offset(offset).limit(page_size).all()

    return PaginatedMessages(
        total=total,
        page=page,
        page_size=page_size,
        items=messages,
    )


# ── Atomic Intervention ─────────────────────────────────────────────────

@router.post("/intervene/{session_id}")
def intervene_in_conversation(
    session_id: str,
    background_tasks: BackgroundTasks,          # ← FIXED: was asyncio.create_task
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
):
    """
    Atomic agent takeover. Prevents race conditions via conditional DB update.
    Tenant isolation ensures agents can only intervene in their own tenant's sessions.
    """
    query_id = session_id
    id_filter = (ChatSession.session_uuid == query_id) if is_valid_uuid(query_id) else (ChatSession.session_id == query_id)

    stmt = (
        update(ChatSession)
        .where(
            id_filter,
            ChatSession.tenant_id == current_user.tenant_id,  # ← TENANT GUARD
            ChatSession.session_status == SessionStatus.ACTIVE,
            ChatSession.conversation_mode == ConversationMode.BOT,
            ChatSession.is_deleted == False,
        )
        .values(
            conversation_mode=ConversationMode.HUMAN,
            assigned_agent_id=current_user.id,
            assigned_at=datetime.now(dt_timezone.utc),
            is_locked=True,
            version=ChatSession.version + 1,
        )
    )

    result = db.execute(stmt)
    db.commit()

    if result.rowcount == 0:
        existing = (
            db.query(ChatSession)
            .filter(
                id_filter,
                ChatSession.tenant_id == current_user.tenant_id,
            )
            .first()
        )
        if not existing:
            raise HTTPException(status_code=404, detail="Session not found")
        if existing.conversation_mode == ConversationMode.HUMAN:
            raise HTTPException(
                status_code=409,
                detail=f"Already claimed by agent ID {existing.assigned_agent_id}",
            )
        raise HTTPException(
            status_code=400,
            detail="Unable to intervene in this session (possibly closed or deleted)",
        )

    logger.info({"event": "agent_intervened", "session_id": session_id, "agent_id": current_user.id})

    # ── Safe async broadcast via BackgroundTasks (works in sync routes) ──
    async def _broadcast():
        await socket_manager.broadcast_event(
            "SESSION_UPDATED",
            {
                "session_id": session_id,
                "current_mode": ConversationMode.HUMAN,
                "agent_name": current_user.full_name,
            },
        )

    background_tasks.add_task(_broadcast)

    return {
        "success": True,
        "message": "Successfully intervened. You are now handling this chat.",
        "session_id": session_id,
        "current_mode": ConversationMode.HUMAN,
        "agent_name": current_user.full_name,
    }


# ── Connect Agent (legacy endpoint kept for compatibility) ──────────────

@router.post("/connect/{session_id}")
def connect_to_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
):
    """Agent claims a waiting conversation. Enforces single-agent lock."""
    query_id = session_id
    id_filter = ChatSession.session_id == query_id
    if is_valid_uuid(query_id):
        id_filter = (ChatSession.session_uuid == query_id) | (ChatSession.session_id == query_id)

    chat_session = (
        db.query(ChatSession)
        .filter(
            id_filter,
            ChatSession.tenant_id == current_user.tenant_id,
            ChatSession.session_status == SessionStatus.ACTIVE,
            ChatSession.is_deleted == False,
        )
        .first()
    )

    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")

    if chat_session.is_locked and chat_session.assigned_agent_id != current_user.id:
        raise HTTPException(
            status_code=409,
            detail="This conversation is already being handled by another agent.",
        )

    chat_session.conversation_mode = ConversationMode.HUMAN
    chat_session.assigned_agent_id = current_user.id
    chat_session.assigned_at = datetime.now(dt_timezone.utc)
    chat_session.is_locked = True
    chat_session.version += 1
    db.commit()

    logger.info({"event": "agent_connected", "session_id": session_id, "agent_id": current_user.id})

    return {
        "success": True,
        "message": "Connected to conversation.",
        "session_id": session_id,
        "agent_id": current_user.id,
    }


# ── Close Conversation ──────────────────────────────────────────────────

@router.post("/close/{session_id}")
async def close_conversation(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
):
    """Agent ends their turn. Hands back control to BOT. Tenant-isolated."""
    from app.models.chat_message import ChatMessage

    query_id = session_id
    id_filter = ChatSession.session_id == query_id
    if is_valid_uuid(query_id):
        id_filter = (ChatSession.session_uuid == query_id) | (ChatSession.session_id == query_id)

    # Verify session belongs to this tenant
    session = (
        db.query(ChatSession)
        .filter(
            id_filter,
            ChatSession.tenant_id == current_user.tenant_id,
            ChatSession.is_deleted == False,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 🚨 HANDBACK LOGIC: Do NOT close session, just revert mode
    session.conversation_mode = ConversationMode.BOT
    session.agent_joined = False
    session.assigned_agent_id = None
    session.is_locked = False
    session.updated_at = datetime.now(dt_timezone.utc)
    # Ensure is_active remains True
    session.is_active = True
    session.session_status = SessionStatus.ACTIVE

    # 1. Create Enterprise Handback Message
    agent_name_display = current_user.full_name or current_user.email.split('@')[0] or "An agent"
    handback_text = f"Agent {agent_name_display} has left the conversation. Our assistant will continue to help you."
    handback_msg = ChatMessage(
        session_id=session.session_id,
        message_type="bot",
        message_text=handback_text,
        created_at_utc=datetime.now(dt_timezone.utc),
        created_at_local=datetime.now(dt_timezone.utc),
    )
    db.add(handback_msg)
    db.commit()

    # 2. Broadcast to client (so they see the bot is back)
    await socket_manager.broadcast_event(
        "NEW_MESSAGE",
        {
            "session_id": session_id,
            "message": handback_text,
            "sender": "bot",
            "timestamp": datetime.now(dt_timezone.utc).isoformat()
        }
    )
    
    # 3. Notify CRM list (remove from agent's active list or update status)
    session_item = _assemble_items([(session, None)], db)[0]
    await socket_manager.broadcast_event(
        "SESSION_UPDATED", 
        session_item.model_dump(mode="json")
    )

    logger.info({"event": "agent_handback", "session_id": session_id, "agent_id": current_user.id})
    return {"success": True, "message": "Handed back to bot."}

    logger.info({"event": "conversation_closed", "session_id": session_id, "closed_by": current_user.id})
    return {"success": True, "message": "Conversation closed and client notified."}


# ── WebSocket Dashboard Sync (Hardened) ────────────────────────────────

@router.websocket("/ws/dashboard")
async def dashboard_websocket(
    websocket: WebSocket,
    token: Optional[str] = Query(default=None),  # Pass as ?token=<jwt>
    db: Session = Depends(get_db),
):
    """
    Real-time dashboard updates.
    SECURITY: JWT validated from query param before connection is accepted.
    Hardcoded user_id has been REMOVED.
    """
    # ── Validate JWT before accepting connection ─────────────────────
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id: Optional[int] = int(payload.get("sub"))
        token_version: Optional[int] = payload.get("token_version")
        if not user_id or token_version is None:
            raise JWTError("Invalid payload")
    except (JWTError, ValueError, TypeError):
        await websocket.close(code=4001, reason="Invalid authentication token")
        return

    # ── Verify user is still active + token version valid ───────────
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active or user.token_version != token_version:
        await websocket.close(code=4003, reason="Access denied")
        return

    await socket_manager.connect(websocket, user_id)
    logger.info({"event": "dashboard_ws_connected", "user_id": user_id})

    try:
        while True:
            await websocket.receive_text()  # Keep alive
    except WebSocketDisconnect:
        socket_manager.disconnect(websocket, user_id)
        logger.info({"event": "dashboard_ws_disconnected", "user_id": user_id})
    except Exception as e:
        logger.error(f"Dashboard WebSocket error for user {user_id}: {e}")
        socket_manager.disconnect(websocket, user_id)


# ── Sales Controls ──────────────────────────────────────────────────────

@router.post("/toggle-priority/{session_id}")
async def toggle_priority(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
):
    """
    Toggles lead_status between 'PRIORITY' and 'Cold'.
    """
    row = db.query(ChatSession, User.full_name.label("agent_name")).outerjoin(User, ChatSession.assigned_agent_id == User.id).filter(
        ChatSession.session_uuid == session_id,
        ChatSession.tenant_id == current_user.tenant_id,
        ChatSession.is_deleted == False
    ).first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session, agent_name = row
    session.lead_status = "PRIORITY" if session.lead_status != "PRIORITY" else "Cold"
    db.commit()
    
    # Broadcast update
    session_item = _assemble_items([(session, agent_name)], db)[0]
    await socket_manager.broadcast_event("SESSION_UPDATED", session_item.model_dump(mode="json"))
    
    return {"success": True, "lead_status": session.lead_status}


@router.post("/toggle-spam/{session_id}")
async def toggle_spam(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
):
    """
    Toggles spam_flag and updates lead_status.
    """
    row = db.query(ChatSession, User.full_name.label("agent_name")).outerjoin(User, ChatSession.assigned_agent_id == User.id).filter(
        ChatSession.session_uuid == session_id,
        ChatSession.tenant_id == current_user.tenant_id,
        ChatSession.is_deleted == False
    ).first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session, agent_name = row
    session.spam_flag = not session.spam_flag
    if session.spam_flag:
        session.lead_status = "SPAM"
    else:
        session.lead_status = "Cold"
    
    db.commit()
    
    # Broadcast update
    session_item = _assemble_items([(session, agent_name)], db)[0]
    await socket_manager.broadcast_event("SESSION_UPDATED", session_item.model_dump(mode="json"))
    
    return {"success": True, "spam_flag": session.spam_flag, "lead_status": session.lead_status}


@router.post("/block-visitor/{session_id}")
async def block_visitor(
    session_id: str,
    reason: Optional[str] = Query(default="Abusive behavior"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
):
    """
    Blocks visitor by IP and Fingerprint, then closes the session.
    """
    row = db.query(ChatSession, User.full_name.label("agent_name")).outerjoin(User, ChatSession.assigned_agent_id == User.id).filter(
        ChatSession.session_uuid == session_id,
        ChatSession.tenant_id == current_user.tenant_id,
        ChatSession.is_deleted == False
    ).first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session, agent_name = row
    
    # 1. Create block record
    block = BlockedVisitor(
        tenant_id=current_user.tenant_id,
        ip_address=session.initial_ip,
        visitor_fingerprint=session.visitor_fingerprint,
        reason=reason
    )
    db.add(block)
    
    # 2. Close session
    session.session_status = SessionStatus.CLOSED
    session.is_active = False
    session.ended_at_utc = datetime.now(dt_timezone.utc)
    
    db.commit()
    
    # 3. Broadcast update
    session_item = _assemble_items([(session, agent_name)], db)[0]
    await socket_manager.broadcast_event("SESSION_UPDATED", session_item.model_dump(mode="json"))
    
    return {"success": True, "message": "Visitor blocked and session closed."}
@router.post("/update-lead/{session_id}")
async def update_lead_info(
    session_id: str,
    update_data: LeadUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(1)),
):
    """
    Manually or automatically update lead contact information.
    extracted from chat or manually entered by agent.
    """
    # 1. Find the session and its lead
    # 🚨 SECURITY: Handle SQL Server UNIQUEIDENTIFIER conversion safety
    if is_valid_uuid(session_id):
        session = db.query(ChatSession).filter(
            (ChatSession.session_uuid == session_id) | 
            (ChatSession.session_id == session_id),
            ChatSession.tenant_id == current_user.tenant_id,
            ChatSession.is_deleted == False
        ).first()
    else:
        session = db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.tenant_id == current_user.tenant_id,
            ChatSession.is_deleted == False
        ).first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if not session.lead_id:
        # Create lead if missing (though session_id usually covers this)
        lead = Lead(id=session.session_id, tenant_id=current_user.tenant_id)
        db.add(lead)
        session.lead_id = lead.id
    else:
        lead = db.query(Lead).filter(Lead.id == session.lead_id).first()
        if not lead:
             lead = Lead(id=session.lead_id, tenant_id=current_user.tenant_id)
             db.add(lead)

    # 2. Update fields
    if update_data.name: lead.name = update_data.name
    if update_data.email: lead.email = update_data.email
    if update_data.phone: lead.phone = update_data.phone
    if update_data.company: lead.company = update_data.company
    
    db.commit()
    db.refresh(lead)

    # 3. Broadcast update to all dashboard viewers
    agent_name = db.query(User.full_name).filter(User.id == session.assigned_agent_id).scalar()
    session_item = _assemble_items([(session, agent_name)], db)[0]
    await socket_manager.broadcast_event("SESSION_UPDATED", session_item.model_dump(mode="json"))

    return {"success": True, "lead": {
        "name": lead.name,
        "email": lead.email,
        "phone": lead.phone,
        "company": lead.company
    }}
