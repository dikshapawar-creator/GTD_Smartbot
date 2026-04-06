import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from sqlalchemy import select, and_, or_, func, text
from app.core.tenant_resolver import TenantResolver
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone


from app.db.session import get_db
from app.services.live_chat_socket import get_live_chat_socket
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode
from app.models.chat_message import ChatMessage
from app.api.deps import get_current_user
from app.core.timezone_utils import format_ist_datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live-chat", tags=["live-chat"])

def get_active_sessions_sync(db: Session, tenant_id: int) -> List[ChatSession]:
    """Get all active sessions for the live chat dashboard (synchronous version)."""
    from app.services.session_service import SessionService
    session_service = SessionService(db)
    return session_service.get_active_sessions(tenant_id=tenant_id)


@router.get("/conversations")
async def get_conversations(
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get all active conversations for the live chat dashboard."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    logger.info(f"📊 Fetching conversations for tenant {tenant_id} (user: {current_user.id}, super_admin: {getattr(current_user, 'is_super_admin', False)})")
    
    # PROACTIVE CLEANUP: Consolidate any duplicate sessions before fetching
    from sqlalchemy import select, func
    
    # Find all visitor UUIDs that have multiple active sessions
    duplicate_visitors_stmt = (
        select(ChatSession.visitor_uuid)
        .where(
            ChatSession.tenant_id == tenant_id,
            ChatSession.session_status.in_([SessionStatus.ACTIVE, SessionStatus.BOT, SessionStatus.HUMAN]),
            ChatSession.is_deleted == False
        )
        .group_by(ChatSession.visitor_uuid)
        .having(func.count(ChatSession.id) > 1)
    )
    
    duplicate_visitors = db.execute(duplicate_visitors_stmt).scalars().all()
    
    # Consolidate each visitor's sessions
    for visitor_uuid in duplicate_visitors:
        logger.info(f"🔧 Consolidating duplicate sessions for visitor {visitor_uuid}")
        consolidate_visitor_sessions(db, visitor_uuid, tenant_id)
    
    sessions = get_active_sessions_sync(db, tenant_id=tenant_id)
    logger.info(f"📊 Found {len(sessions)} active sessions for tenant {tenant_id}")
    
    # Convert to frontend format
    conversations = []
    from app.services.websocket_manager import manager
    
    for session in sessions:
        conversations.append(format_session_for_crm(session))
    
    return conversations

@router.get("/session-details/{session_uuid}")
async def get_session_details(
    session_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get session details including tenant_id for super admin tenant switching."""
    # Find the session
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.is_deleted == False
            )
        )
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Check if user has access to this session's tenant
    if not current_user.is_super_admin:
        tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
        if session.tenant_id != tenant_id:
            raise HTTPException(status_code=403, detail="Access denied")
    
    # Return full formatted session for consistency
    return format_session_for_crm(session)


@router.get("/analytics")
async def get_analytics(
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get live chat analytics."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    sessions = get_active_sessions_sync(db, tenant_id=tenant_id)
    
    active_visitors = len([s for s in sessions if s.session_status == SessionStatus.ACTIVE])
    agent_chats = len([s for s in sessions if s.current_mode == ConversationMode.HUMAN])
    spam_visitors = len([s for s in sessions if s.spam_flag])
    
    # Calculate average lead score
    scores = [s.lead_score for s in sessions if s.lead_score]
    avg_lead_score = sum(scores) / len(scores) if scores else 0
    
    return {
        "active_visitors": active_visitors,
        "agent_chats": agent_chats,
        "spam_visitors": spam_visitors,
        "avg_lead_score": avg_lead_score
    }


@router.get("/messages/{session_uuid}")
async def get_messages(
    session_uuid: str,
    request: Request,
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get messages for a specific session, including consolidated history."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    
    # Find the most recent session by visitor UUID or session ID
    stmt = (
        select(ChatSession)
        .where(
            and_(
                (ChatSession.visitor_uuid == session_uuid) | (ChatSession.session_id == session_uuid),
                ChatSession.tenant_id == tenant_id,
                ChatSession.is_deleted == False  # Include any non-deleted session for message history
            )
        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalars().first()  # Use first() instead of scalar_one_or_none() to handle multiple results
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # CRITICAL FIX: Consolidate sessions for this visitor first, but do NOT reactivate if closed
    consolidated_session = consolidate_visitor_sessions(db, session.visitor_uuid, tenant_id, reactivate_closed=False)
    
    # Get messages for ALL sessions belonging to this visitor or lead
    # This unified view helps agents see the full context of returning visitors
    
    # Base filter: same visitor UUID
    filter_cond = (ChatSession.visitor_uuid == session.visitor_uuid)
    
    # Expanded filter: same lead ID (cross-device context)
    if session.lead_id:
        filter_cond = or_(filter_cond, ChatSession.lead_id == session.lead_id)
        
    stmt = (
        select(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.session_id)
        .where(
            and_(
                filter_cond,
                ChatSession.tenant_id == tenant_id,
                ChatSession.is_deleted == False
            )
        )
        .order_by(ChatMessage.created_at_utc.desc())  # 🔥 Get LATEST first for proper pagination
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    
    result = db.execute(stmt)
    messages = list(result.scalars().all())
    
    # 🔃 Reverse back to ASC for the frontend chat view (oldest at top)
    messages.reverse()
    
    logger.info(f"GET_MESSAGES: Found {len(messages)} messages for visitor {session_uuid} (linked search: {'lead_id=' + str(session.lead_id) if session.lead_id else 'uuid only'})")
    
    # Convert to frontend format
    items = []
    for msg in messages:
        items.append({
            "id": msg.id,
            "session_id": session_uuid,  # Use visitor_uuid for consistency
            "message_type": msg.message_type,
            "message_text": msg.message_text,
            "sender_user_id": msg.sender_user_id,
            "sender_name": msg.sender_name,
            "sender_email": msg.sender_email,
            "created_at_utc": msg.created_at_utc.isoformat() if msg.created_at_utc else None,
            "created_at_ist": format_ist_datetime(msg.created_at_utc),
            "is_read": bool(getattr(msg, 'is_read', False)),
            "read_at": msg.read_at.isoformat() if getattr(msg, 'read_at', None) else None,
        })
    
    return {"items": items}


@router.post("/read/{session_uuid}")
async def mark_messages_read(
    session_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Agent marks all user messages in a session as read, triggering double-tick on client."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    now = datetime.utcnow()

    # Find the session
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.tenant_id == tenant_id
            )
        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    chat_session = result.scalars().first()

    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Bulk mark all unread USER messages as read
    try:
        db.query(ChatMessage).filter(
            ChatMessage.session_id == chat_session.session_id,
            ChatMessage.message_type == 'user',
            ChatMessage.is_read == False
        ).update({"is_read": True, "read_at": now}, synchronize_session=False)
        db.commit()
    except Exception:
        # Column may not exist yet in older DBs - ignore gracefully
        db.rollback()

    # Broadcast MESSAGE_READ event to client WebSocket
    try:
        from app.core.socket_manager import socket_manager
        await socket_manager.broadcast_event(
            "MESSAGE_READ",
            {
                "session_id": session_uuid,
                "read_by": "agent",
                "read_at": now.isoformat()
            },
            tenant_id=tenant_id
        )
    except Exception as e:
        logger.warning(f"MESSAGE_READ broadcast failed: {e}")

    return {"status": "ok", "read_at": now.isoformat()}


@router.post("/intervene/{session_uuid}")
async def intervene_session(
    session_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Agent takes over bot conversation."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.is_deleted == False
            )
        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update session for agent takeover
    session.current_mode = ConversationMode.HUMAN
    session.conversation_mode = ConversationMode.HUMAN
    session.session_status = SessionStatus.ACTIVE
    session.agent_name = current_user.full_name or current_user.email or "Agent"
    session.assigned_agent_id = current_user.id
    session.assigned_agent_email = current_user.email
    session.assigned_agent_name = current_user.full_name
    session.is_locked = True
    session.agent_joined = True
    session.agent_joined_at = datetime.utcnow()
    session.last_activity_at = datetime.utcnow()
    session.last_activity_utc = datetime.utcnow()
    
    db.commit()
    db.refresh(session)
    
    # Get recent message history for agent context (consolidated history)
    from app.models.chat_message import ChatMessage
    from sqlalchemy import or_
    
    # Base filter: current session
    hist_cond = (ChatMessage.session_id == session.session_id)
    
    # Expanded filter: same visitor UUID or lead ID (cross-session context)
    # Using a join for more robust matching of all related messages
    recent_messages = (
        db.query(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.session_id)
        .filter(
            or_(
                ChatSession.visitor_uuid == session.visitor_uuid,
                ChatSession.lead_id == session.lead_id if session.lead_id else False
            ),
            ChatSession.tenant_id == tenant_id,
            ChatSession.is_deleted == False
        )
        .order_by(ChatMessage.created_at_utc.desc())
        .limit(50)  # Agent needs more context after takeover
        .all()
    )
    
    # Format messages for agent
    message_history = []
    for msg in reversed(recent_messages):  # Reverse to get chronological order
        message_history.append({
            "id": msg.id,
            "message_type": msg.message_type,
            "message_text": msg.message_text,
            "created_at_ist": msg.created_at_ist,
            "sender_name": msg.sender_name,
            "is_read": msg.is_read
        })
    
    # Notify via WebSocket using existing infrastructure
    try:
        socket_manager = get_live_chat_socket()
        if socket_manager:
            # Notify CRM
            await socket_manager.notify_session_updated(session, session.tenant_id)
            
            # 🔥 ALSO notify Leads Table for real-time sync across pages
            await socket_manager.broadcast_event(
                "LEAD_UPDATED",
                {
                    "id": session.lead_id,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                },
                tenant_id=session.tenant_id
            )
            
        # Also broadcast agent takeover with message history
        from app.core.socket_manager import socket_manager as ws_manager
        await ws_manager.broadcast_event(
            "AGENT_TAKEOVER",
            {
                "session_uuid": session_uuid,
                "session_id": session.session_id,
                "agent_name": current_user.full_name,
                "message_history": message_history,
                "timestamp": datetime.utcnow().isoformat()
            },
            tenant_id=tenant_id
        )
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {
        "message": "Agent takeover successful",
        "session_id": session.session_id,
        "message_history": message_history
    }


@router.post("/message/{session_uuid}")
async def send_message(
    session_uuid: str,
    message_data: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Send message as agent."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.session_status == SessionStatus.ACTIVE
            )

        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found")
    
    # Create message
    message = ChatMessage(
        tenant_id=session.tenant_id,
        session_id=session.session_id,
        message_type="agent",
        message_text=message_data.get("message", ""),
        sender_user_id=current_user.id,
        sender_name=current_user.full_name,
        sender_email=current_user.email,
        created_at=datetime.utcnow(),
        created_at_utc=datetime.utcnow(),
        created_at_local=datetime.utcnow()
    )
    
    db.add(message)
    
    # Update session
    session.last_activity_at = datetime.utcnow()
    session.last_activity_utc = datetime.utcnow()
    session.message_count = (session.message_count or 0) + 1
    
    db.commit()
    db.refresh(message)
    
    # Notify via WebSocket using existing infrastructure
    try:
        socket_manager = get_live_chat_socket()
        if socket_manager:
            client_msg_id = message_data.get("client_msg_id")
            await socket_manager.notify_message(message, session, session.tenant_id, client_msg_id=client_msg_id)
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {"message": "Message sent successfully"}


@router.post("/close/{session_uuid}")
async def close_session(
    session_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Close a chat session."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    # Find the most recent active session by visitor UUID (any non-closed status)
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.session_status.in_([SessionStatus.ACTIVE, SessionStatus.BOT, SessionStatus.HUMAN, SessionStatus.WAITING]),
                ChatSession.is_deleted == False
            )

        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found")
    
    # Update session to close it - but reset mode to BOT for potential reactivation
    session.session_status = SessionStatus.CLOSED
    session.conversation_mode = ConversationMode.BOT
    session.current_mode = ConversationMode.BOT
    # Clear assignment to allow bot takeover on next message
    session.assigned_agent_id = None
    session.assigned_agent_email = None
    session.assigned_agent_name = None
    session.agent_name = None
    session.agent_joined = False
    session.is_locked = False
    
    session.closed_by_agent_id = current_user.id
    session.closed_by_agent_email = current_user.email
    session.closed_by_agent_name = current_user.full_name
    session.agent_closed_at = datetime.utcnow()
    session.last_activity_at = datetime.utcnow()
    session.last_activity_utc = datetime.utcnow()
    session.ended_at_utc = datetime.utcnow()
    session.ended_at_local = datetime.utcnow()
    
    db.commit()
    db.refresh(session)
    
    # Notify CRM via WebSocket
    try:
        socket_manager = get_live_chat_socket()
        if socket_manager:
            await socket_manager.notify_session_updated(session, session.tenant_id)
    except Exception as e:
        print(f"WebSocket notification failed: {e}")

    # 🔴 Notify the CLIENT widget that this session was closed by agent
    # This allows the widget to reset and accept new messages as a fresh session
    try:
        from app.services.websocket_manager import manager
        await manager.send_to_client(session_uuid, {
            "type": "CHAT_ENDED",
            "reason": "agent_closed",
            "message": "This conversation was closed by an agent. You can start a new chat anytime.",
            "session_id": session_uuid
        })
    except Exception as e:
        logger.warning(f"Failed to notify client of session close: {e}")
    
    return {"message": "Session closed successfully"}


@router.post("/toggle-priority/{session_uuid}")
async def toggle_priority(
    session_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Toggle priority status of a session."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.session_status == SessionStatus.ACTIVE
            )

        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found")
    
    # Toggle priority (assuming we have a priority field or use lead_status)
    current_status = getattr(session, 'lead_status', 'NORMAL')
    session.lead_status = 'PRIORITY' if current_status != 'PRIORITY' else 'NORMAL'
    session.last_activity_at = datetime.utcnow()
    
    db.commit()
    
    # Notify via WebSocket using existing infrastructure
    try:
        socket_manager = get_live_chat_socket()
        if socket_manager:
            await socket_manager.notify_session_updated(session, session.tenant_id)
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {"message": "Priority status updated"}


@router.post("/toggle-spam/{session_uuid}")
async def toggle_spam(
    session_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Toggle spam flag of a session."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.session_status == SessionStatus.ACTIVE
            )

        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found")
    
    # Toggle spam flag
    session.spam_flag = not (session.spam_flag or False)
    session.last_activity_at = datetime.utcnow()
    
    db.commit()
    
    # Notify via WebSocket using existing infrastructure
    try:
        socket_manager = get_live_chat_socket()
        if socket_manager:
            await socket_manager.notify_session_updated(session, session.tenant_id)
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {"message": "Spam status updated"}


@router.post("/block-visitor/{session_uuid}")
async def block_visitor(
    session_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Block a visitor and close their session."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.tenant_id == tenant_id,
                ChatSession.session_status == SessionStatus.ACTIVE
            )

        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found")
    
    # Mark as blocked and close
    session.spam_flag = True
    session.session_status = SessionStatus.CLOSED
    session.is_locked = False
    session.last_activity_at = datetime.utcnow()
    
    # ✅ Persist the block to blocked_visitors table so it can be listed/unblocked
    from app.models.blocked import BlockedVisitor
    client_ip = session.initial_ip or session.last_ip
    visitor_fp = session.visitor_fingerprint

    if client_ip:
        # Avoid duplicates
        existing_block = db.query(BlockedVisitor).filter(
            BlockedVisitor.tenant_id == tenant_id,
            BlockedVisitor.ip_address == client_ip
        ).first()
        if not existing_block:
            block_record = BlockedVisitor(
                tenant_id=tenant_id,
                ip_address=client_ip,
                visitor_fingerprint=visitor_fp,
                reason=f"Blocked by agent via CRM (session: {session_uuid})"
            )
            db.add(block_record)

    db.commit()
    
    return {"message": "Visitor blocked successfully", "ip": client_ip}


def _get_lead_status(score: int) -> str:
    """Convert numeric score to status string."""
    if score >= 70:
        return "HOT"
    elif score >= 40:
        return "WARM"
    else:
        return "COLD"


def format_session_for_crm(session: ChatSession) -> dict:
    """Format a single session for CRM broadcast."""
    ip_meta = session.ip_metadata_dict
    from app.services.websocket_manager import manager
    
    return {
        "session_id": session.session_id,  # Use string session_id instead of BigInteger id
        "session_uuid": session.visitor_uuid,  # Keep using visitor_uuid for frontend compatibility
        "session_status": session.session_status,
        "current_mode": session.current_mode,
        "agent_name": session.agent_name,
        "assigned_agent_id": session.assigned_agent_id,
        "assigned_agent_email": session.assigned_agent_email,
        "assigned_agent_name": session.assigned_agent_name,
        "agent_joined_at": session.agent_joined_at.isoformat() if session.agent_joined_at else None,
        "closed_by_agent_id": session.closed_by_agent_id,
        "closed_by_agent_email": session.closed_by_agent_email,
        "closed_by_agent_name": session.closed_by_agent_name,
        "agent_closed_at": session.agent_closed_at.isoformat() if session.agent_closed_at else None,
        "is_locked": session.is_locked,
        "is_online": manager.has_client(session.visitor_uuid),
        "lead_name": getattr(session.lead, 'name', None) or session.lead_name,
        "lead_company": getattr(session.lead, 'company', None) or session.lead_company,
        "lead_email": getattr(session.lead, 'email', None) or session.lead_email,
        "lead_phone": getattr(session.lead, 'phone', None) or session.lead_phone,
        "trade_type": getattr(session.lead, 'trade_type', None),
        "country_interested": getattr(session.lead, 'country_interested', None),
        "product": getattr(session.lead, 'product', None),
        "requirement_type": getattr(session.lead, 'requirement_type', None),
        "website": getattr(session.lead, 'website', None),
        "lead_score": session.lead_score or 0,
        "lead_status": getattr(session.lead, 'status', None) or _get_lead_status(session.lead_score or 0),
        "spam_flag": session.spam_flag or False,
        "last_message_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
        "message_count": session.message_count or 0,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "duration_seconds": session.duration_seconds or 0,
        "repeat_visitor": False,
        "previous_session_count": 0,
        "initial_ip": ip_meta.get("ip") or session.initial_ip,
        "country": session.country,
        "city": session.city,
        "browser": ip_meta.get("browser") or session.browser or "Unknown",
        "os": ip_meta.get("os") or session.os or "Unknown",
        "device_type": ip_meta.get("device_type") or session.device_type or "desktop",
        "language": session.language or "en",
        "created_at_ist": format_ist_datetime(session.created_at),
        "last_message_ist": format_ist_datetime(session.last_activity_at),
        "lead_insights": session.lead_insights,
        "server_time_utc": datetime.utcnow().isoformat(),
    }


@router.post("/cleanup-empty-sessions")
async def cleanup_empty_sessions_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Clean up sessions with 0 messages (admin only)."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    from sqlalchemy import select, delete, func, update
    from datetime import datetime, timedelta
    
    try:
        # Fix message count inconsistencies first
        stmt = (
            select(
                ChatSession.id,
                ChatSession.message_count,
                func.count(ChatMessage.id).label('actual_count')
            )
            .outerjoin(ChatMessage, ChatSession.session_id == ChatMessage.session_id)
            .group_by(ChatSession.id, ChatSession.message_count)
            .having(ChatSession.message_count != func.count(ChatMessage.id))
        )
        
        result = db.execute(stmt)
        inconsistent_sessions = result.all()
        
        fixed_count = 0
        for session_id, stored_count, actual_count in inconsistent_sessions:
            update_stmt = (
                update(ChatSession)
                .where(ChatSession.id == session_id)
                .values(message_count=actual_count)
            )
            db.execute(update_stmt)
            fixed_count += 1
        
        # Delete empty sessions older than 1 hour
        cutoff_time = datetime.utcnow() - timedelta(hours=1)
        
        empty_sessions_stmt = (
            select(ChatSession.session_id)
            .where(
                ChatSession.message_count == 0,
                ChatSession.created_at < cutoff_time
            )
        )
        
        empty_result = db.execute(empty_sessions_stmt)
        empty_session_ids = [row[0] for row in empty_result.all()]
        
        deleted_count = 0
        if empty_session_ids:
            delete_stmt = delete(ChatSession).where(ChatSession.session_id.in_(empty_session_ids))
            delete_result = db.execute(delete_stmt)
            deleted_count = delete_result.rowcount
        
        db.commit()
        
        return {
            "message": "Cleanup completed successfully",
            "fixed_message_counts": fixed_count,
            "deleted_empty_sessions": deleted_count
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")


def consolidate_visitor_sessions(db: Session, visitor_uuid: str, tenant_id: int, reactivate_closed: bool = True) -> Optional[ChatSession]:
    """
    Consolidate duplicate sessions for a visitor and return the most recent active session.
    This prevents duplicate queue cards in the live chat dashboard.
    """
    from sqlalchemy import select
    from datetime import datetime
    
    # Look for ALL sessions for this visitor (including closed ones to consolidate properly)
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.visitor_uuid == visitor_uuid,
            ChatSession.tenant_id == tenant_id,
            ChatSession.is_deleted == False
        )
        .order_by(ChatSession.created_at.desc())
    )
    
    result = db.execute(stmt)
    sessions = list(result.scalars().all())
    
    if not sessions:
        return None
    
    # Find the most recent session that has activity or is active
    keep_session = None
    for session in sessions:
        if session.session_status in [SessionStatus.ACTIVE, SessionStatus.BOT, SessionStatus.HUMAN]:
            keep_session = session
            break
    
    # If no active session found, use the most recent one
    if not keep_session:
        keep_session = sessions[0]
        if reactivate_closed:
            keep_session.session_status = SessionStatus.ACTIVE
            keep_session.current_mode = ConversationMode.BOT
            keep_session.conversation_mode = ConversationMode.BOT
            keep_session.is_locked = False
            keep_session.agent_joined = False
            keep_session.spam_flag = False  # Ensure returning unblocked users aren't still flagged as spam
            keep_session.last_activity_at = datetime.utcnow()
            keep_session.last_activity_utc = datetime.utcnow()
    
    # CRITICAL FIX: Merge lead information from all sessions
    # This ensures that returning visitors are recognized as existing leads
    lead_info_merged = False
    for session in sessions:
        if session.id != keep_session.id:
            # Transfer lead information if the kept session doesn't have it but this session does
            if not keep_session.lead_name and session.lead_name:
                keep_session.lead_name = session.lead_name
                lead_info_merged = True
            if not keep_session.lead_email and session.lead_email:
                keep_session.lead_email = session.lead_email
                lead_info_merged = True
            if not keep_session.lead_phone and session.lead_phone:
                keep_session.lead_phone = session.lead_phone
                lead_info_merged = True
            if not keep_session.lead_company and session.lead_company:
                keep_session.lead_company = session.lead_company
                lead_info_merged = True
            if not keep_session.lead_id and session.lead_id:
                keep_session.lead_id = session.lead_id
                lead_info_merged = True
            if not keep_session.lead_score and session.lead_score:
                keep_session.lead_score = session.lead_score
                lead_info_merged = True
            if not keep_session.lead_insights and session.lead_insights:
                keep_session.lead_insights = session.lead_insights
                lead_info_merged = True
    
    # Close all other sessions for this visitor
    duplicate_sessions = [s for s in sessions if s.id != keep_session.id]
    
    if duplicate_sessions:
        logger.info(f"Consolidating sessions for visitor {visitor_uuid}. Keeping {keep_session.session_id}, closing {len(duplicate_sessions)} others.")
        
        if lead_info_merged:
            logger.info(f"Merged lead information for visitor {visitor_uuid}: name={keep_session.lead_name}, email={keep_session.lead_email}")
        
        for duplicate in duplicate_sessions:
            duplicate.session_status = SessionStatus.CLOSED
            duplicate.current_mode = ConversationMode.BOT
            duplicate.conversation_mode = ConversationMode.BOT
            duplicate.is_locked = False
            duplicate.agent_joined = False
            duplicate.ended_at_utc = datetime.utcnow()
            duplicate.ended_at_local = datetime.utcnow()
        
        db.commit()
    
    return keep_session


@router.get("/history")
async def get_history(
    request: Request,
    page: int = 1,
    page_size: int = 25,
    status_filter: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get paginated conversation history with session consolidation by visitor."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    logger.info(f"FETCH_HISTORY: tenant_id={tenant_id}, status_filter={status_filter}, date_from={date_from}, date_to={date_to}")
    
    # CRITICAL FIX: Consolidate sessions by visitor_uuid first
    # This prevents multiple sessions for the same visitor from appearing in history
    
    # Step 1: Proactively consolidate any duplicate sessions before querying
    from sqlalchemy import func, and_, select, distinct
    
    # Find visitors with multiple sessions
    duplicate_visitors_stmt = (
        select(ChatSession.visitor_uuid)
        .where(
            ChatSession.tenant_id == tenant_id,
            ChatSession.is_deleted == False
        )
        .group_by(ChatSession.visitor_uuid)
        .having(func.count(ChatSession.id) > 1)
    )
    
    duplicate_visitors = db.execute(duplicate_visitors_stmt).scalars().all()
    
    # Consolidate each visitor's sessions
    total_consolidated = 0
    for visitor_uuid in duplicate_visitors:
        consolidated_session = consolidate_visitor_sessions(db, visitor_uuid, tenant_id, reactivate_closed=False)
        if consolidated_session:
            total_consolidated += 1
    
    if total_consolidated > 0:
        logger.info(f"FETCH_HISTORY: Consolidated {total_consolidated} duplicate visitor sessions")
    
    # Step 2: Get unique visitors with their most recent session
    # Use a window function approach instead of complex joins
    from sqlalchemy import text
    
    # Build base conditions
    base_conditions = [
        ChatSession.tenant_id == tenant_id,
        ChatSession.is_deleted == False
    ]
    
    if country:
        base_conditions.append(ChatSession.country == country)
    
    # Status filter — handle both 'ALL' and 'all'
    if status_filter and str(status_filter).upper() != 'ALL':
        if status_filter.lower() == 'active':
            base_conditions.append(ChatSession.session_status == 'active')
        elif status_filter.lower() == 'ended':
            base_conditions.append(ChatSession.session_status == 'ended')
    
    # Date filters
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            base_conditions.append(ChatSession.created_at >= date_from_dt)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            base_conditions.append(ChatSession.created_at <= date_to_dt)
        except ValueError:
            pass
    
    # Get all sessions matching criteria, then deduplicate by visitor_uuid in Python
    # This is simpler and more reliable than complex SQL joins
    all_sessions_stmt = (
        select(ChatSession)
        .where(and_(*base_conditions))
        .order_by(ChatSession.visitor_uuid, ChatSession.last_activity_at.desc())
    )
    
    all_sessions = db.execute(all_sessions_stmt).scalars().all()
    
    # Deduplicate by visitor_uuid - keep only the most recent session per visitor
    unique_sessions = {}
    for session in all_sessions:
        visitor_uuid = session.visitor_uuid
        if visitor_uuid not in unique_sessions:
            unique_sessions[visitor_uuid] = session
        else:
            # Keep the session with the most recent activity
            if session.last_activity_at > unique_sessions[visitor_uuid].last_activity_at:
                unique_sessions[visitor_uuid] = session
    
    # Convert to list and sort by last_activity_at descending
    sessions_list: List[Any] = list(unique_sessions.values())
    sessions_list.sort(key=lambda x: x.last_activity_at, reverse=True)
    
    total = len(sessions_list)
    logger.info(f"FETCH_HISTORY: Total unique visitors found: {total}")
    
    # Apply pagination
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_sessions = sessions_list[start_idx:end_idx] if sessions_list else []
    
    logger.info(f"FETCH_HISTORY: Retrieved {len(paginated_sessions)} consolidated sessions")
    
    # Format sessions for frontend
    items = []
    for session in paginated_sessions:
        items.append(format_session_for_crm(session))
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.get("/detail/{session_uuid}")
async def get_session_detail(
    session_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get detailed session information."""
    """Get detailed session information."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    import logging
    
    logger = logging.getLogger(__name__)
    logger.info(f"Looking for session with UUID: {session_uuid}")
    
    stmt = select(ChatSession).where(
        and_(
            (ChatSession.visitor_uuid == session_uuid) | (ChatSession.session_id == session_uuid),
            ChatSession.tenant_id == tenant_id
        )
    )
    result = db.execute(stmt)
    session = result.scalars().first()
    
    if not session:
        logger.error(f"Session not found for UUID: {session_uuid}")
        raise HTTPException(status_code=404, detail=f"Session not found for UUID: {session_uuid}")
    
    logger.info(f"Found session: {session.session_id}, visitor_uuid: {session.visitor_uuid}")
    return format_session_for_crm(session)


@router.post("/update-lead/{session_uuid}")
async def update_lead(
    session_uuid: str,
    data: Dict[str, Any],
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Manually update lead data for a session from CRM."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    from sqlalchemy import select, or_
    stmt = select(ChatSession).where(
        ((ChatSession.visitor_uuid == session_uuid) | (ChatSession.session_id == session_uuid)),
        ChatSession.tenant_id == tenant_id
    )
    result = db.execute(stmt)
    session = result.scalars().first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Update session lead fields directly
    if "name" in data: session.lead_name = data["name"]
    if "email" in data: session.lead_email = data["email"]
    if "phone" in data: session.lead_phone = data["phone"]
    if "company" in data: session.lead_company = data["company"]
    
    # If no Lead exists but we have basic info, create one
    if not session.lead and (session.lead_email or session.lead_phone or data.get("email") or data.get("phone")):
        from app.models.lead import Lead, LeadStatus
        new_lead = Lead(
            tenant_id=tenant_id,
            name=data.get("name") or session.lead_name or "Unknown",
            email=data.get("email") or session.lead_email or "unknown@example.com",
            phone=data.get("phone") or session.lead_phone or "0000000000",
            company=data.get("company") or session.lead_company,
            session_id=session.session_id,
            status=data.get("status") or LeadStatus.NEW.value
        )
        db.add(new_lead)
        db.flush()
        session.lead_id = new_lead.id
        session.is_lead = True
    
    # Also update the linked Lead record if it exists
    if session.lead:
        if "name" in data: session.lead.name = data["name"]
        if "email" in data: session.lead.email = data["email"]
        if "phone" in data: session.lead.phone = data["phone"]
        if "company" in data: session.lead.company = data["company"]
        if "trade_type" in data: session.lead.trade_type = data["trade_type"]
        if "country_interested" in data: session.lead.country_interested = data["country_interested"]
        if "product" in data: session.lead.product = data["product"]
        if "requirement_type" in data: session.lead.requirement_type = data["requirement_type"]
        if "status" in data: session.lead.status = data["status"]
        if "website" in data: session.lead.website = data["website"]
        session.is_lead = True
    
    session.updated_at = datetime.utcnow()
    db.commit()
    
    # Notify via WebSocket to refresh CRM view
    try:
        socket_manager = get_live_chat_socket()
        if socket_manager:
            await socket_manager.notify_session_updated(session, session.tenant_id)
    except Exception:
        pass
        
    return {"status": "success", "message": "Lead updated successfully"}


@router.post("/test-message/{session_uuid}")
async def test_message_to_client(
    session_uuid: str,
    message_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Test endpoint to send a message directly to client WebSocket."""
    
    # Check if client is connected
    from app.services.websocket_manager import manager
    
    # Try multiple variations of the session ID
    session_variations = [
        session_uuid,
        session_uuid.lower(),
        session_uuid.upper(),
    ]
    
    client_found = False
    target_sid = None
    
    for variation in session_variations:
        if manager.has_client(variation):
            client_found = True
            target_sid = variation
            break
    
    if not client_found:
        return {
            "success": False,
            "error": "No client connected",
            "session_uuid": session_uuid,
            "tried_variations": session_variations,
            "available_clients": list(manager._clients.keys()),
            "available_agents": list(manager._agents.keys())
        }
    
    # Send test message to client
    test_message = message_data.get("message", "Test message from CRM")
    
    try:
        await manager.send_to_client(target_sid, {
            "type": "message",
            "message": test_message,
            "sender": "agent",
            "purpose": "chatbot",
            "msg_id": f"test_{int(datetime.utcnow().timestamp())}",
            "message_status": "delivered",
            "session_id": session_uuid,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return {
            "success": True,
            "message": "Test message sent successfully",
            "target_session": target_sid,
            "original_session": session_uuid
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to send message: {str(e)}",
            "target_session": target_sid
        }
async def debug_session(
    session_uuid: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Debug endpoint to check session status and WebSocket connections."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    
    # Find the session
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                (ChatSession.visitor_uuid == session_uuid) | (ChatSession.session_id == session_uuid),
                ChatSession.is_deleted == False
            )
        )
    )
    result = db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        return {"error": "Session not found", "session_uuid": session_uuid}
    
    # Check WebSocket connections
    from app.services.websocket_manager import manager
    has_client = manager.has_client(session_uuid)
    has_agent = manager.has_agent(session_uuid)
    
    # Also check with normalized (lowercase) UUID
    normalized_uuid = session_uuid.lower()
    has_client_normalized = manager.has_client(normalized_uuid)
    has_agent_normalized = manager.has_agent(normalized_uuid)
    
    return {
        "session_found": True,
        "session_id": session.session_id,
        "visitor_uuid": session.visitor_uuid,
        "tenant_id": session.tenant_id,
        "session_status": session.session_status,
        "current_mode": session.current_mode,
        "conversation_mode": session.conversation_mode,
        "agent_joined": session.agent_joined,
        "assigned_agent_id": session.assigned_agent_id,
        "is_locked": session.is_locked,
        "websocket_connections": {
            "has_client_original": has_client,
            "has_agent_original": has_agent,
            "has_client_normalized": has_client_normalized,
            "has_agent_normalized": has_agent_normalized,
            "all_clients": list(manager._clients.keys()),
            "all_agents": list(manager._agents.keys())
        }
    }


@router.get("/debug/session/{session_uuid}")
async def debug_session(
    session_uuid: str,
    db: Session = Depends(get_db)
):
    """Debug endpoint to check session status and WebSocket connections."""
    # Find all sessions with this UUID (there might be duplicates)
    from sqlalchemy import select
    stmt = (
        select(ChatSession)
        .where(
            (ChatSession.visitor_uuid == session_uuid) | (ChatSession.session_id == session_uuid),
            ChatSession.is_deleted == False
        )
        .order_by(ChatSession.last_activity_at.desc())  # Get most recent first
    )
    result = db.execute(stmt)
    sessions = list(result.scalars().all())
    
    if not sessions:
        return {"error": "Session not found", "session_uuid": session_uuid}
    
    # Use the most recent session
    session = sessions[0]
    
    # Check WebSocket connections
    from app.services.websocket_manager import manager
    has_client = manager.has_client(session_uuid)
    has_agent = manager.has_agent(session_uuid)
    
    # Also check with normalized (lowercase) UUID
    normalized_uuid = session_uuid.lower()
    has_client_normalized = manager.has_client(normalized_uuid)
    has_agent_normalized = manager.has_agent(normalized_uuid)
    
    return {
        "session_found": True,
        "total_sessions_found": len(sessions),
        "using_most_recent": True,
        "session_id": session.session_id,
        "visitor_uuid": session.visitor_uuid,
        "tenant_id": session.tenant_id,
        "session_status": session.session_status,
        "current_mode": session.current_mode,
        "conversation_mode": session.conversation_mode,
        "agent_joined": session.agent_joined,
        "assigned_agent_id": session.assigned_agent_id,
        "is_locked": session.is_locked,
        "last_activity_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
        "websocket_connections": {
            "has_client_original": has_client,
            "has_agent_original": has_agent,
            "has_client_normalized": has_client_normalized,
            "has_agent_normalized": has_agent_normalized,
            "all_clients": list(manager._clients.keys()),
            "all_agents": list(manager._agents.keys())
        },
        "all_sessions": [
            {
                "session_id": s.session_id,
                "visitor_uuid": s.visitor_uuid,
                "session_status": s.session_status,
                "current_mode": s.current_mode,
                "last_activity_at": s.last_activity_at.isoformat() if s.last_activity_at else None,
                "created_at": s.created_at.isoformat() if s.created_at else None
            } for s in sessions
        ]
    }


@router.get("/server-time")
async def get_server_time():
    """Get current server time for synchronization."""
    from datetime import datetime
    return {
        "server_time_utc": datetime.utcnow().isoformat() + "Z"
    }


@router.post("/cleanup-empty")
async def cleanup_empty_sessions_endpoint(
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Cleanup empty sessions endpoint."""
    tenant_id = TenantResolver.resolve_admin_tenant(db, request, current_user)
    # Remove sessions with no messages and older than 1 hour
    
    # Remove sessions with no messages and older than 1 hour
    cutoff_time = datetime.utcnow() - timedelta(hours=1)
    
    empty_sessions_query = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.message_count == 0,
                ChatSession.created_at < cutoff_time
            )
        )
    )
    
    empty_sessions = db.execute(empty_sessions_query).scalars().all()
    
    removed_count = 0
    for session in empty_sessions:
        db.delete(session)
        removed_count += 1
    
    if removed_count > 0:
        db.commit()
    
    return {
        "message": f"Removed {removed_count} empty sessions",
        "removed_count": removed_count
    }