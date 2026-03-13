"""
SessionService — Enterprise DB-level session lifecycle management.
Features: inactivity-based expiry, activity tracking, and engagement metrics.
"""
import logging
import uuid
from datetime import datetime, timezone as dt_timezone, timedelta
from uuid import uuid4
from typing import Optional

import pytz
from sqlalchemy.orm import Session

from app.models.chat_session import ChatSession, SessionStatus, ConversationMode

from app.models.chat_message import ChatMessage
from app.core.config import settings

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    """Return current UTC datetime (timezone-naive for SQL Server)."""
    return datetime.now(dt_timezone.utc).replace(tzinfo=None)


def _to_local(utc_dt: datetime, tz_str: str) -> datetime:
    """Convert UTC datetime to local timezone (naive)."""
    try:
        tz = pytz.timezone(tz_str)
        utc_aware = pytz.utc.localize(utc_dt)
        local_aware = utc_aware.astimezone(tz)
        return local_aware.replace(tzinfo=None)
    except Exception:
        return utc_dt


def create_session(
    db: Session,
    ip_address: str,
    country: str,
    city: str,
    timezone_str: str,
    user_agent: str = "Unknown",
    browser: str = "Unknown",
    os_name: str = "Unknown",
    device_type: str = "Desktop",
    fingerprint: Optional[str] = None,
    tenant_id: int = 1,
    visitor_uuid: Optional[str] = None,
    lead_id: Optional[str] = None,
) -> ChatSession:
    """Creates a new session with senior IP & metadata tracking."""
    import time
    from sqlalchemy.exc import OperationalError

    def _do_insert(db: Session) -> ChatSession:
        s_uuid = uuid4()
        session_id = str(s_uuid)
        now_utc = _now_utc()
        now_local = _to_local(now_utc, timezone_str)
        
        # Normalize visitor_uuid
        v_uuid = str(visitor_uuid) if visitor_uuid else str(uuid.uuid4())

        logger.info(f"Creating session with visitor_uuid: {v_uuid}, lead_id: {lead_id}")

        chat_session = ChatSession(
            session_id=session_id,
            session_uuid=s_uuid,
            tenant_id=tenant_id,
            visitor_uuid=v_uuid,
            lead_id=lead_id, # Link to existing lead if provided
            initial_ip=ip_address,
            last_seen_ip=ip_address,
            last_seen_at=now_utc,
            visitor_fingerprint=fingerprint,
            user_agent=user_agent,
            browser=browser,
            os=os_name,
            device_type=device_type,
            country=country,
            city=city,
            timezone=timezone_str,
            started_at_utc=now_utc,
            started_at_local=now_local,
            last_activity_utc=now_utc,
            total_messages=0,
            session_status=SessionStatus.ACTIVE,
            conversation_mode=ConversationMode.BOT,
            status="ACTIVE",
            is_deleted=False,
        )
        db.add(chat_session)
        db.commit()
        db.refresh(chat_session)
        return chat_session

    try:
        chat_session = _do_insert(db)
    except OperationalError as e:
        # ── Transient connection failure: invalidate + retry once ────────
        # Covers: ('08S01', 'Communication link failure') and similar
        logger.warning(
            f"session_service.create_session: Transient DB error, invalidating connection and retrying. Error: {e}"
        )
        try:
            db.rollback()
            # Invalidate the specific connection instead of disposing the whole pool
            try:
                db.connection().invalidate()
            except Exception:
                pass
        except Exception:
            pass
        time.sleep(0.5)  # Brief pause to allow pool to establish a fresh connection
        # Re-raise if the retry also fails — error will bubble up to the API handler
        chat_session = _do_insert(db)

    session_id = chat_session.session_id
    logger.info({
        "event": "session_created",
        "session_id": session_id,
        "tenant_id": tenant_id,
        "ip": ip_address,
        "timestamp": _now_utc().isoformat()
    })
    return chat_session


def get_active_session(db: Session, session_id: str, tenant_id: Optional[int] = None) -> Optional[ChatSession]:
    """
    Look up a session and check for inactivity-based expiry.
    """
    q = db.query(ChatSession).filter(
        ChatSession.session_uuid == uuid.UUID(session_id), 
        ChatSession.session_status == SessionStatus.ACTIVE,
        ChatSession.is_deleted == False
    )
    if tenant_id is not None:
        q = q.filter(ChatSession.tenant_id == tenant_id)
        
    chat_session = q.first()

    if not chat_session:
        return None

    # Check for inactivity expiry
    now_utc = _now_utc()
    expiry_limit = timedelta(minutes=settings.SESSION_EXPIRY_MINUTES)
    
    if now_utc - chat_session.last_activity_utc > expiry_limit:
        logger.info({
            "event": "session_expired_inactivity",
            "session_id": session_id,
        })
        close_session(db, session_id, tenant_id)
        return None

    return chat_session


def close_session(db: Session, session_id: str, tenant_id: Optional[int] = None) -> bool:
    """Mark as CLOSED and calculate duration metric."""
    q = (
        db.query(ChatSession)
        .filter(ChatSession.session_uuid == uuid.UUID(session_id), ChatSession.is_deleted == False)
    )
    if tenant_id is not None:
        q = q.filter(ChatSession.tenant_id == tenant_id)
        
    chat_session = q.first()
    if not chat_session or chat_session.session_status == SessionStatus.CLOSED:
        return False

    now_utc = _now_utc()
    now_local = _to_local(now_utc, chat_session.timezone or "UTC")

    chat_session.session_status = SessionStatus.CLOSED
    chat_session.ended_at_utc = now_utc
    chat_session.ended_at_local = now_local
    chat_session.is_locked = False
    
    # Calculate duration
    duration = (now_utc - chat_session.started_at_utc).total_seconds()
    chat_session.duration_seconds = int(duration)

    db.commit()
    logger.info({"event": "session_closed", "session_id": session_id})
    return True


def update_chat_state(db: Session, chat_session: ChatSession, new_state: str) -> None:
    chat_session.chat_state = new_state
    chat_session.last_activity_utc = _now_utc()
    db.commit()


def save_message(
    db: Session,
    chat_session: ChatSession,
    message_text: str,
    message_type: str,
) -> ChatMessage:
    """
    Persist message, update activity, increment total_messages, and handle versioning.
    """
    now_utc = _now_utc()
    now_local = _to_local(now_utc, chat_session.timezone or "UTC")

    # Create message
    msg = ChatMessage(
        session_id=chat_session.session_id,
        message_type=message_type,
        message_text=message_text,
        created_at_utc=now_utc,
        created_at_local=now_local,
    )
    db.add(msg)

    # Update session metrics and activity
    chat_session.last_activity_utc = now_utc
    chat_session.total_messages = (chat_session.total_messages or 0) + 1
    
    # Optimistic locking increment
    chat_session.version += 1

    db.commit()
    return msg


def trigger_agent_takeover(db: Session, session_id: str, lead_id: Optional[str] = None) -> bool:
    """
    Force transition to HUMAN mode and link lead.
    Sets agent_joined=True so the bot completely stops replying.
    """
    chat_session = (
        db.query(ChatSession)
        .filter(
            ChatSession.session_uuid == uuid.UUID(session_id), 
            ChatSession.session_status == SessionStatus.ACTIVE,
            ChatSession.is_deleted == False
        )
        .first()
    )
    if chat_session:
        # 🔥 Hard Takeover: Disable Bot, Enable Human
        chat_session.conversation_mode = ConversationMode.HUMAN
        chat_session.agent_joined = True
        chat_session.status = "human_required"
        chat_session.last_activity_utc = _now_utc()
        chat_session.updated_at = _now_utc()
        
        if lead_id:
            chat_session.lead_id = lead_id
        
        chat_session.version += 1
        db.commit()

        save_message(
            db, chat_session,
            "An agent has been notified and will review your request.",
            "system",
        )
        logger.info(f"Relational link finalized: session {session_id} -> lead {lead_id}")
        return True
    return False



