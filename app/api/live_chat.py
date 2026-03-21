from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.db.session import get_db
from app.services.live_chat_socket import get_live_chat_socket
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode
from app.models.chat_message import ChatMessage
from app.api.deps import get_current_user
from app.core.timezone_utils import format_ist_datetime

router = APIRouter(prefix="/live-chat", tags=["live-chat"])

def get_active_sessions_sync(db: Session) -> List[ChatSession]:
    """Get all active sessions for the live chat dashboard (synchronous version)."""
    from sqlalchemy import select, and_, or_
    from datetime import datetime, timedelta
    
    # Define stale cutoff (1 hour of inactivity)
    stale_cutoff = datetime.utcnow() - timedelta(hours=1)
    
    # We want sessions that are:
    # 1. ACTIVE or BOT status
    # 2. AND NOT deleted
    # 3. AND (Connected via WS OR Active in the last 1 hour)
    
    # First, get all potentially active sessions from DB
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.session_status == SessionStatus.ACTIVE,
                ChatSession.is_deleted == False
            )
        )
        .order_by(ChatSession.last_activity_at.desc())
    )
    
    result = db.execute(stmt)
    sessions = list(result.scalars().all())
    
    # Filter for online or recent activity
    from app.services.websocket_manager import manager
    
    filtered_sessions = []
    for s in sessions:
        is_online = manager.has_client(s.visitor_uuid)
        is_recent = s.last_activity_at >= stale_cutoff if s.last_activity_at else False
        
        if is_online or is_recent:
            filtered_sessions.append(s)
            
    return filtered_sessions


@router.get("/conversations")
async def get_conversations(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get all active conversations for the live chat dashboard."""
    sessions = get_active_sessions_sync(db)
    
    # Convert to frontend format
    conversations = []
    from app.services.websocket_manager import manager
    
    for session in sessions:
        # Get IP metadata safely
        ip_meta = session.ip_metadata_dict
        
        conversations.append({
            "session_id": session.id,
            "session_uuid": session.visitor_uuid,
            "session_status": session.session_status,
            "current_mode": session.current_mode,
            "agent_name": session.agent_name,
            "is_locked": session.is_locked,
            "is_online": manager.has_client(session.visitor_uuid),
            "lead_name": session.lead_name or f"Visitor #{session.visitor_uuid[-6:].upper()}",
            "lead_company": session.lead_company,
            "lead_email": session.lead_email,
            "lead_phone": session.lead_phone,
            "lead_score": session.lead_score or 0,
            "lead_status": _get_lead_status(session.lead_score or 0),
            "spam_flag": session.spam_flag or False,
            "last_message_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
            "message_count": session.message_count or 0,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "repeat_visitor": False,
            "previous_session_count": 0,
            "initial_ip": ip_meta.get("ip") or session.initial_ip,
            "country": session.country,
            "city": session.city,
            "browser": ip_meta.get("browser") or session.browser or "Unknown",
            "os": ip_meta.get("os") or session.os or "Unknown",
            "device_type": ip_meta.get("device_type") or session.device_type or "desktop",
            "created_at_ist": format_ist_datetime(session.created_at),
            "last_message_ist": format_ist_datetime(session.last_activity_at),
            "server_time_utc": datetime.utcnow().isoformat(),  # For time sync
        })
    
    return conversations


@router.get("/analytics")
async def get_analytics(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get live chat analytics."""
    sessions = get_active_sessions_sync(db)
    
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
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get messages for a specific session."""
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.session_status.in_([SessionStatus.ACTIVE, SessionStatus.CLOSED])  # Include closed sessions for message history
            )
        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalars().first()  # Use first() instead of scalar_one_or_none() to handle multiple results
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Get messages for ALL sessions belonging to this visitor
    # This unified view helps agents see the full context of returning visitors
    stmt = (
        select(ChatMessage)
        .join(ChatSession, ChatMessage.session_id == ChatSession.session_id)
        .where(
            and_(
                ChatSession.visitor_uuid == session.visitor_uuid,
                ChatSession.is_deleted == False
            )
        )
        .order_by(ChatMessage.created_at.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    
    result = db.execute(stmt)
    messages = list(result.scalars().all())
    
    # Convert to frontend format
    items = []
    for msg in messages:
        items.append({
            "id": msg.id,
            "session_id": session_uuid,
            "message_type": msg.message_type,
            "message_text": msg.message_text,
            "created_at_utc": msg.created_at.isoformat() if msg.created_at else None,
            "created_at_ist": format_ist_datetime(msg.created_at),
        })
    
    return {"items": items}


@router.post("/intervene/{session_uuid}")
async def intervene_session(
    session_uuid: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Agent takes over bot conversation."""
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
                ChatSession.session_status.in_(["ACTIVE", "BOT"])
            )
        )
        .order_by(ChatSession.last_activity_at.desc())
        .limit(1)
    )
    result = db.execute(stmt)
    session = result.scalar_one_or_none()
    
    if not session:
        raise HTTPException(status_code=404, detail="Active session not found")
    
    # Update session for agent takeover
    session.current_mode = ConversationMode.HUMAN
    session.conversation_mode = ConversationMode.HUMAN
    session.session_status = SessionStatus.ACTIVE
    session.agent_name = current_user.email or "Agent"  # Use direct attribute access
    session.is_locked = True
    session.agent_joined = True
    session.last_activity_at = datetime.utcnow()
    session.last_activity_utc = datetime.utcnow()
    
    db.commit()
    db.refresh(session)
    
    # Notify via WebSocket using existing infrastructure
    try:
        socket_manager = get_live_chat_socket()
        if socket_manager:
            await socket_manager.notify_session_updated(session, "default")
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {"message": "Agent takeover successful"}


@router.post("/message/{session_uuid}")
async def send_message(
    session_uuid: str,
    message_data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Send message as agent."""
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
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
    
    # Create message - fix the foreign key issue
    message = ChatMessage(
        session_id=session.session_id,  # Use session_id (string) not id (BigInteger)
        session_uuid=session.visitor_uuid,
        message_type="agent",
        message_text=message_data.get("message", ""),
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
            await socket_manager.notify_message(message, session, "default")
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {"message": "Message sent successfully"}


@router.post("/close/{session_uuid}")
async def close_session(
    session_uuid: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Close a chat session."""
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
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
    
    # Update session to close it
    session.session_status = SessionStatus.CLOSED
    session.is_locked = False
    session.agent_joined = False
    session.last_activity_at = datetime.utcnow()
    session.last_activity_utc = datetime.utcnow()
    session.ended_at_utc = datetime.utcnow()
    session.ended_at_local = datetime.utcnow()
    
    db.commit()
    db.refresh(session)
    
    # Notify via WebSocket using existing infrastructure
    try:
        socket_manager = get_live_chat_socket()
        if socket_manager:
            await socket_manager.notify_session_updated(session, "default")
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {"message": "Session closed successfully"}


@router.post("/toggle-priority/{session_uuid}")
async def toggle_priority(
    session_uuid: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Toggle priority status of a session."""
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
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
            await socket_manager.notify_session_updated(session, "default")
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {"message": "Priority status updated"}


@router.post("/toggle-spam/{session_uuid}")
async def toggle_spam(
    session_uuid: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Toggle spam flag of a session."""
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
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
            await socket_manager.notify_session_updated(session, "default")
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {"message": "Spam status updated"}


@router.post("/block-visitor/{session_uuid}")
async def block_visitor(
    session_uuid: str,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Block a visitor and close their session."""
    # Find the most recent active session by visitor UUID
    from sqlalchemy import select, and_
    stmt = (
        select(ChatSession)
        .where(
            and_(
                ChatSession.visitor_uuid == session_uuid,
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
    
    db.commit()
    
    # Notify via WebSocket using existing infrastructure
    try:
        socket_manager = get_live_chat_socket()
        if socket_manager:
            await socket_manager.notify_session_updated(session, "default")
    except Exception as e:
        print(f"WebSocket notification failed: {e}")
        # Continue without WebSocket - REST API still works
    
    return {"message": "Visitor blocked successfully"}


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
        "is_locked": session.is_locked,
        "is_online": manager.has_client(session.visitor_uuid),
        "lead_name": session.lead_name or f"Visitor #{session.visitor_uuid[-6:].upper()}",
        "lead_company": session.lead_company,
        "lead_email": session.lead_email,
        "lead_phone": session.lead_phone,
        "lead_score": session.lead_score or 0,
        "lead_status": _get_lead_status(session.lead_score or 0),
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
        "server_time_utc": datetime.utcnow().isoformat(),
    }


@router.post("/cleanup-empty-sessions")
async def cleanup_empty_sessions_endpoint(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Clean up sessions with 0 messages (admin only)."""
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


def consolidate_visitor_sessions(db: Session, visitor_uuid: str) -> Optional[ChatSession]:
    """
    Consolidate duplicate sessions for a visitor and return the most recent active session.
    This prevents duplicate queue cards in the live chat dashboard.
    """
    from sqlalchemy import select
    from datetime import datetime, timedelta
    
    # Look for active sessions for this visitor in the last 30 minutes
    cutoff = datetime.utcnow() - timedelta(minutes=30)
    
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.visitor_uuid == visitor_uuid,
            ChatSession.session_status == SessionStatus.ACTIVE
        )
        .order_by(ChatSession.created_at.desc())
    )
    
    result = db.execute(stmt)
    sessions = list(result.scalars().all())
    
    if not sessions:
        return None
    
    # If we have multiple sessions, keep the most recent one and close the others
    if len(sessions) > 1:
        keep_session = sessions[0]  # Most recent
        duplicate_sessions = sessions[1:]  # Older duplicates
        
        for duplicate in duplicate_sessions:
            duplicate.session_status = SessionStatus.CLOSED
            duplicate.ended_at_utc = datetime.utcnow()
            duplicate.ended_at_local = datetime.utcnow()
        
        db.commit()
        return keep_session
    
    return sessions[0]


@router.get("/history")
async def get_history(
    page: int = 1,
    page_size: int = 25,
    status_filter: str = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get paginated conversation history."""
    from sqlalchemy import select, and_, func
    from datetime import datetime
    
    # Build base query
    conditions = []
    
    # Status filter
    if status_filter and status_filter != 'ALL':
        if status_filter == 'ACTIVE':
            conditions.append(ChatSession.session_status == SessionStatus.ACTIVE)
        elif status_filter == 'CLOSED':
            conditions.append(ChatSession.session_status == SessionStatus.CLOSED)
    
    # Date filters
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
            conditions.append(ChatSession.created_at >= date_from_dt)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
            conditions.append(ChatSession.created_at <= date_to_dt)
        except ValueError:
            pass
    
    # Count total records
    count_stmt = select(func.count(ChatSession.id))
    if conditions:
        count_stmt = count_stmt.where(and_(*conditions))
    
    total = db.execute(count_stmt).scalar()
    
    # Get paginated results
    stmt = (
        select(ChatSession)
        .order_by(ChatSession.last_activity_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    
    if conditions:
        stmt = stmt.where(and_(*conditions))
    
    result = db.execute(stmt)
    sessions = list(result.scalars().all())
    
    # Format sessions for frontend
    items = []
    for session in sessions:
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
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Get detailed session information."""
    from sqlalchemy import select, String
    import logging
    
    logger = logging.getLogger(__name__)
    logger.info(f"Looking for session with UUID: {session_uuid}")
    
    # Find by session_id/visitor_uuid
    stmt = select(ChatSession).where(
        (ChatSession.visitor_uuid == session_uuid) | (ChatSession.session_id == session_uuid)
    )
    result = db.execute(stmt)
    session = result.scalars().first()
    
    if not session:
        logger.error(f"Session not found for UUID: {session_uuid}")
        raise HTTPException(status_code=404, detail=f"Session not found for UUID: {session_uuid}")
    
    logger.info(f"Found session: {session.session_id}, visitor_uuid: {session.visitor_uuid}")
    return format_session_for_crm(session)


@router.get("/server-time")
async def get_server_time():
    """Get current server time for synchronization."""
    from datetime import datetime
    return {
        "server_time_utc": datetime.utcnow().isoformat() + "Z"
    }


@router.post("/cleanup-empty")
async def cleanup_empty_sessions_endpoint(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Cleanup empty sessions endpoint."""
    from datetime import datetime, timedelta
    from sqlalchemy import select, and_
    
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