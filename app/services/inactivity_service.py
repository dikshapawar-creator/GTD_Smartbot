import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Dict
from app.db.session import SessionLocal
from app.models.chat_session import ChatSession
from app.models.chat_message import ChatMessage
from app.services import session_service
from app.services.websocket_manager import manager as ws_manager

logger = logging.getLogger(__name__)

# Global tracking to prevent thundering herd / multiple tasks per session
# session_id -> latest_activity_timestamp
active_monitors: Dict[str, datetime] = {}
# session_id -> boolean (is a task already running?)
running_tasks: set = set()

async def send_inactivity_message(session_id: str, last_activity_timestamp: datetime):
    """
    Monitors a session for inactivity.
    Uses a debouncing strategy to ensure only one task runs per session.
    """
    # Normalize timestamp
    if last_activity_timestamp and last_activity_timestamp.tzinfo is not None:
        last_activity_timestamp = last_activity_timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    
    # 1. Update the latest known activity time for this session
    active_monitors[session_id] = last_activity_timestamp
    
    # 2. If a monitor task is already running, this one can exit immediately.
    # The running task will check active_monitors when it wakes up.
    if session_id in running_tasks:
        return
        
    running_tasks.add(session_id)
    logger.debug(f"Monitor: Started single monitor task for session {session_id}")

    try:
        while True:
            current_target = active_monitors.get(session_id)
            if not current_target:
                return

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            diff = (now - current_target).total_seconds()
            
            if diff >= 60:
                # We have been inactive for at least 60 seconds
                break
            
            # Still active or recently used. Wait the remaining time + jitter
            wait_time = 60 - diff + random.uniform(0.5, 2.0)
            logger.debug(f"Monitor: {session_id} active {diff:.1f}s ago. Sleeping {wait_time:.1f}s")
            await asyncio.sleep(wait_time)

        # 3. Proceed with Nudge check (Only one task ever reaches here per inactivity period)
        db = SessionLocal()
        try:
            # Re-fetch session to check for latest activity and mode
            chat_session = db.query(ChatSession).filter(
                (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id)
            ).first()
            
            if not chat_session:
                return

            # Case-insensitive check for BOT mode
            current_mode = (chat_session.conversation_mode or "").upper()
            if current_mode != "BOT":
                logger.debug(f"Monitor: Session {session_id} mode is {current_mode}. Skipping nudge.")
                return

            # Final verification of timestamp from DB
            db_ts = chat_session.last_activity_utc
            if db_ts and db_ts.tzinfo is not None:
                db_ts = db_ts.astimezone(timezone.utc).replace(tzinfo=None)

            target_ts = active_monitors.get(session_id)
            if db_ts and target_ts and db_ts > target_ts:
                # Database has newer activity than what we were tracking.
                # This task should loop again or exit if another task was started.
                # But since this is the ONLY running task, we update and loop.
                active_monitors[session_id] = db_ts
                return # Next iterate of while True will handle it

            # Generate Nudge
            from app.models.intent_config import IntentConfig
            config = db.query(IntentConfig).filter(
                IntentConfig.intent_key == "INACTIVITY_NUDGE",
                IntentConfig.tenant_id == chat_session.tenant_id
            ).first()
            
            inactivity_msg = config.response_text if (config and config.response_text) else (
                "We’ve received your message and will get back to you soon.\n\n"
                "For more details, feel free to reach us anytime:\n"
                "💬- https://wa.me/918527376675\n"
                "📞 WhatsApp: +91 8527376675\n\n"
                "We’ll be happy to assist you with complete support.\n\n"
            )
            
            # Prevent double-nudging
            last_msg = db.query(ChatMessage).filter(ChatMessage.session_id == chat_session.session_id).order_by(ChatMessage.created_at_utc.desc()).first()
            if last_msg and (last_msg.message_text == inactivity_msg):
                logger.debug(f"Monitor: Nudge already sent for {session_id}.")
                return

            logger.info(f"Monitor: Sending nudge for {chat_session.session_id}")
            
            # Persist and Broadcast
            new_msg = session_service.save_message(db, chat_session, inactivity_msg, "bot")
            db.commit()
            
            crm_session_id = str(chat_session.visitor_uuid)
            from app.core.socket_manager import socket_manager
            await socket_manager.broadcast_event("NEW_MESSAGE", {
                "session_id": crm_session_id,
                "message": inactivity_msg,
                "sender": "bot",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, tenant_id=chat_session.tenant_id)
            
            if ws_manager.has_client(crm_session_id.lower()):
                await ws_manager.send_to_client(crm_session_id.lower(), {
                    "type": "message",
                    "message": inactivity_msg,
                    "sender": "bot",
                    "is_inactivity": True
                })
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error in inactivity monitor: {e}")
    finally:
        running_tasks.discard(session_id)
        active_monitors.pop(session_id, None)
