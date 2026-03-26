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
    # Normalize timestamp to naive for comparison (consistent with SQLAlchemy defaults)
    compare_ts = last_activity_timestamp
    if compare_ts and compare_ts.tzinfo is not None:
        compare_ts = compare_ts.astimezone(timezone.utc).replace(tzinfo=None)
    
    logger.info(f"Monitor started for session {session_id}. Target Stamp: {compare_ts}")
    await asyncio.sleep(60)

    db = SessionLocal()
    try:
        # Re-fetch session to check for latest activity
        chat_session = db.query(ChatSession).filter(
            (ChatSession.visitor_uuid == session_id) | (ChatSession.session_id == session_id)
        ).first()
        
        if not chat_session:
            logger.debug(f"Monitor: Session {session_id} not found.")
            return

        # Case-insensitive check for BOT mode
        current_mode = (chat_session.conversation_mode or "").upper()
        if current_mode != "BOT":
            logger.debug(f"Monitor: Session {session_id} is in mode {current_mode}. Skipping nudge.")
            return

        # 🔧 DEBUG: Log identifiers
        logger.debug(f"Monitor Sync: visitor_uuid={chat_session.visitor_uuid}, session_id={chat_session.session_id}")

        # Normalize DB timestamp for comparison
        db_ts = chat_session.last_activity_utc
        if db_ts and db_ts.tzinfo is not None:
            db_ts = db_ts.astimezone(timezone.utc).replace(tzinfo=None)

        # Check if last_activity_utc is still the same as when we started the monitor
        diff_seconds = (db_ts - compare_ts).total_seconds() if db_ts and compare_ts else 100
        logger.debug(f"Monitor Trace: db_ts={db_ts}, compare_ts={compare_ts}, diff={diff_seconds}s")
        
        if diff_seconds < 1.0: # Increased tolerance to 1s for safety
            # Prevent double-nudging
            last_msg = db.query(ChatMessage).filter(ChatMessage.session_id == chat_session.session_id).order_by(ChatMessage.created_at_utc.desc()).first()
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
                "WhatsApp Messenger: More than 2 billion people in over 180 countries use WhatsApp to stay in touch with friends and family, anytime and anywhere."
            )
            
            # Check if the last message is already the inactivity nudge to prevent sending it multiple times
            if last_msg and (last_msg.message_text == inactivity_msg):
                logger.debug(f"Monitor: Nudge already sent for {session_id}.")
                return

            logger.info(f"Monitor: PERSISTING nudge for {chat_session.session_id}")
            
            # 1. Persist to DB
            new_msg = session_service.save_message(db, chat_session, inactivity_msg, "bot")
            db.commit()
            logger.info(f"Monitor: Nudge SAVED (ID: {new_msg.id})")
            
            # 2. Broadcast to CRM Dashboard
            # Use visitor_uuid as the front-end session identifier for CRM
            crm_session_id = str(chat_session.visitor_uuid)
            await socket_manager.broadcast_event(
                "NEW_MESSAGE",
                {
                    "session_id": crm_session_id,
                    "message": inactivity_msg,
                    "sender": "bot",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            )
            logger.info(f"Monitor: Nudge BROADCAST to CRM (Session: {crm_session_id})")
            
            # 3. Push to Client via WebSocket
            if ws_manager.has_client(crm_session_id.lower()):
                await ws_manager.send_to_client(crm_session_id.lower(), {
                    "type": "message",
                    "message": inactivity_msg,
                    "sender": "bot",
                    "is_inactivity": True
                })
                logger.info(f"Monitor: Nudge SENT to Client via WS")
    except Exception as e:
        logger.error(f"Error in inactivity monitor: {e}")
    finally:
        db.close()
