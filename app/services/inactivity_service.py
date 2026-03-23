import asyncio
import logging
from datetime import datetime, timezone
from app.db.session import SessionLocal
from app.models.chat_session import ChatSession
from app.models.chat_message import ChatMessage
from app.services import session_service
from app.core.socket_manager import socket_manager
from app.services.websocket_manager import manager as ws_manager

logger = logging.getLogger(__name__)

async def send_inactivity_message(session_id: str, last_activity_timestamp: datetime):
    """
    Waits 60 seconds and checks if the session is still inactive.
    If yes, sends an inactivity message and persists it.
    Uses its own DB session for background safety.
    """
    logger.info(f"Monitor started for session {session_id} since {last_activity_timestamp}")
    await asyncio.sleep(60)
    
    # Normalize timestamp to naive for comparison (consistent with SQLAlchemy defaults)
    compare_ts = last_activity_timestamp
    if compare_ts and compare_ts.tzinfo is not None:
        compare_ts = compare_ts.astimezone(timezone.utc).replace(tzinfo=None)

    db = SessionLocal()
    try:
        # Re-fetch session to check for latest activity
        chat_session = db.query(ChatSession).filter(
            (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id)
        ).first()
        
        if not chat_session:
            logger.debug(f"Monitor: Session {session_id} not found.")
            return

        if chat_session.conversation_mode != "BOT":
            logger.debug(f"Monitor: Session {session_id} is in mode {chat_session.conversation_mode}. Skipping nudge.")
            return

        # Normalize DB timestamp for comparison
        db_ts = chat_session.last_activity_utc
        if db_ts and db_ts.tzinfo is not None:
            db_ts = db_ts.astimezone(timezone.utc).replace(tzinfo=None)

        # Check if last_activity_utc is still the same as when we started the monitor
        diff_seconds = abs((db_ts - compare_ts).total_seconds()) if db_ts and compare_ts else 100
        
        if diff_seconds < 1:
            # Prevent double-nudging if the last message already contains the link
            last_msg = db.query(ChatMessage).filter(ChatMessage.session_id == chat_session.session_id).order_by(ChatMessage.created_at_utc.desc()).first()
            if last_msg and "https://wa.me/918527376675" in (last_msg.message_text or ""):
                logger.debug(f"Monitor: Nudge already sent for {session_id}.")
                return

            inactivity_msg = "We’ve received your message and will get back to you soon.\n\nFor more details, feel free to reach us anytime:\n💬 https://wa.me/918527376675\n📞 WhatsApp: +91 8527376675\n\nWe’ll be happy to assist you with complete support."
            
            logger.info(f"Sending inactivity message to session {session_id} (Diff: {diff_seconds}s)")
            
            # 1. Persist to DB
            session_service.save_message(db, chat_session, inactivity_msg, "bot")
            db.commit()
            
            # 2. Broadcast to CRM Dashboard
            await socket_manager.broadcast_event(
                "NEW_MESSAGE",
                {
                    "session_id": str(chat_session.visitor_uuid),
                    "message": inactivity_msg,
                    "sender": "bot",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            )
            
            # 3. Push to Client via WebSocket if they are connected
            if ws_manager.has_client(session_id.lower()):
                await ws_manager.send_to_client(session_id.lower(), {
                    "type": "message",
                    "message": inactivity_msg,
                    "sender": "bot",
                    "is_inactivity": True
                })
    except Exception as e:
        logger.error(f"Error in inactivity monitor: {e}")
    finally:
        db.close()
