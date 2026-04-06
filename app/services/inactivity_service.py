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
            
            if diff < 60:
                # Still active or recently used. Wait the remaining time + jitter
                wait_time = 60 - diff + random.uniform(0.5, 2.0)
                logger.debug(f"Monitor: {session_id} active {diff:.1f}s ago. Sleeping {wait_time:.1f}s")
                await asyncio.sleep(wait_time)
                continue

            # We've been inactive for at least 60 seconds — verify against DB
            logger.info(f"Monitor: Session {session_id} inactive for {diff:.1f}s, verifying DB timestamp...")

            db = SessionLocal()
            try:
                # Use either visitor_uuid or session_id to find the session
                chat_session = db.query(ChatSession).filter(
                    (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id),
                    ChatSession.is_deleted == False
                ).first()

                if not chat_session:
                    logger.error(f"Monitor: Session {session_id} not found in DB.")
                    return

                # Allow nudge in both BOT and HUMAN mode
                current_mode = (chat_session.current_mode or "").upper()
                logger.debug(f"Monitor: Session {session_id} mode is {current_mode}. Proceeding with nudge check.")

                # Final DB timestamp check — if DB has newer activity, reset and loop
                db_ts = chat_session.last_activity_utc
                if db_ts and db_ts.tzinfo is not None:
                    db_ts = db_ts.astimezone(timezone.utc).replace(tzinfo=None)

                target_ts = active_monitors.get(session_id)
                if db_ts and target_ts and db_ts > target_ts:
                    active_monitors[session_id] = db_ts
                    logger.info(f"Monitor: Newer DB activity for {session_id} ({db_ts}), resetting timer.")
                    db.close()
                    db = None
                    continue  # Back to top of while loop — safe because we're inside it

                # Look for INACTIVITY_NUDGE or INACTIVITY in DB
                from sqlalchemy import or_
                from app.models.intent_config import IntentConfig
                config = db.query(IntentConfig).filter(
                    or_(IntentConfig.intent_key == "INACTIVITY_NUDGE", IntentConfig.intent_key == "INACTIVITY"),
                    IntentConfig.tenant_id == chat_session.tenant_id,
                    IntentConfig.is_active == True
                ).first()

                inactivity_msg = config.response_text if (config and config.response_text) else (
                    "We've received your message and will get back to you soon.\n\n"
                    "For more details, feel free to reach us anytime:\n"
                    "[💬 Click to WhatsApp](https://wa.me/918527376675)\n\n"
                    "We'll be happy to assist you with complete support."
                )

                # Fix UTF-16 encoding if present
                if inactivity_msg and '\x00' in inactivity_msg:
                    inactivity_msg = inactivity_msg.replace('\x00', '')

                # Prevent double-nudging across the entire session (only send once)
                previous_nudge = db.query(ChatMessage).filter(
                    ChatMessage.session_id == chat_session.session_id,
                    ChatMessage.message_type == "bot",
                    ChatMessage.message_text == inactivity_msg
                ).first()
                
                if previous_nudge:
                    logger.debug(f"Monitor: Nudge already sent once for {session_id}. Will not send again in this session.")
                    return

                logger.info(f"Monitor: Sending nudge for {chat_session.session_id} (visitor_uuid: {chat_session.visitor_uuid})")

                # Persist and Broadcast
                session_service.save_message(db, chat_session, inactivity_msg, "bot")
                db.commit()

                crm_session_id = str(chat_session.visitor_uuid).lower()
                from app.core.socket_manager import socket_manager

                # 1. CRM Broadcast
                await socket_manager.broadcast_event("NEW_MESSAGE", {
                    "session_id": crm_session_id,
                    "message": inactivity_msg,
                    "sender": "bot",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }, tenant_id=chat_session.tenant_id)
                logger.info(f"Monitor: Nudge broadcast to CRM for session {crm_session_id}")

                # 2. Widget WebSocket Delivery
                if ws_manager.has_client(crm_session_id):
                    logger.info(f"Monitor: Client socket found for {crm_session_id}, sending nudge...")
                    await ws_manager.send_to_client(crm_session_id, {
                        "type": "message",
                        "message": inactivity_msg,
                        "sender": "bot",
                        "is_inactivity": True
                    })
                    logger.info(f"Monitor: Nudge sent to client WebSocket for {crm_session_id}")
                else:
                    logger.warning(f"Monitor: No active client socket found for {crm_session_id}. Nudge saved to history only.")

                return  # Done — nudge sent
            finally:
                if db is not None:
                    db.close()

    except Exception as e:
        logger.error(f"Error in inactivity monitor: {e}", exc_info=True)
    finally:
        running_tasks.discard(session_id)
        active_monitors.pop(session_id, None)
