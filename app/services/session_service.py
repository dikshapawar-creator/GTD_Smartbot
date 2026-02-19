"""
SessionService — Enterprise DB-level session lifecycle management.
Features: inactivity-based expiry, activity tracking, and engagement metrics.
"""
import logging
from datetime import datetime, timezone as dt_timezone, timedelta
from uuid import uuid4
from typing import Optional

import pytz
from sqlalchemy.orm import Session

from app.models.chat_session import ChatSession
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
) -> ChatSession:
    """Creates a new session with activity tracking initialized."""
    session_id = str(uuid4())
    now_utc = _now_utc()
    now_local = _to_local(now_utc, timezone_str)

    chat_session = ChatSession(
        session_id=session_id,
        ip_address=ip_address,
        country=country,
        city=city,
        timezone=timezone_str,
        started_at_utc=now_utc,
        started_at_local=now_local,
        last_activity_utc=now_utc, # Initialize activity
        is_active=True,
    )
    db.add(chat_session)
    db.commit()
    db.refresh(chat_session)

    logger.info({
        "event": "session_created",
        "session_id": session_id,
        "ip": ip_address,
        "country": country,
        "timestamp": now_utc.isoformat()
    })
    return chat_session


def get_active_session(db: Session, session_id: str) -> Optional[ChatSession]:
    """
    Look up a session and check for inactivity-based expiry.
    """
    chat_session = (
        db.query(ChatSession)
        .filter(ChatSession.session_id == session_id, ChatSession.is_active == True)
        .first()
    )

    if not chat_session:
        return None

    # Check for inactivity expiry
    now_utc = _now_utc()
    expiry_limit = timedelta(minutes=settings.SESSION_EXPIRY_MINUTES)
    
    if now_utc - chat_session.last_activity_utc > expiry_limit:
        logger.info({
            "event": "session_expired_inactivity",
            "session_id": session_id,
            "last_activity": chat_session.last_activity_utc.isoformat()
        })
        expire_session(db, session_id)
        return None

    return chat_session


def expire_session(db: Session, session_id: str) -> bool:
    """Mark as inactive and calculate duration metric."""
    chat_session = (
        db.query(ChatSession)
        .filter(ChatSession.session_id == session_id)
        .first()
    )
    if not chat_session or not chat_session.is_active:
        return False

    now_utc = _now_utc()
    now_local = _to_local(now_utc, chat_session.timezone or "UTC")

    chat_session.is_active = False
    chat_session.ended_at_utc = now_utc
    chat_session.ended_at_local = now_local
    
    # Calculate duration
    duration = (now_utc - chat_session.started_at_utc).total_seconds()
    chat_session.duration_seconds = int(duration)

    db.commit()
    logger.info({
        "event": "session_ended",
        "session_id": session_id,
        "duration_seconds": chat_session.duration_seconds
    })
    return True


def update_chat_state(db: Session, chat_session: ChatSession, new_state: str) -> None:
    chat_session.chat_state = new_state
    chat_session.last_activity_utc = _now_utc() # Update activity on state change
    db.commit()


def save_message(
    db: Session,
    chat_session: ChatSession,
    message_text: str,
    message_type: str,
) -> ChatMessage:
    """
    Persist message, update activity, and increment total_messages count.
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
    chat_session.total_messages += 1

    db.commit()
    return msg
