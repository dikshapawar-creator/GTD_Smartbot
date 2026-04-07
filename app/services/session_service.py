import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select, and_
from app.models.chat_session import ChatSession, SessionStatus, ConversationMode
from app.models.chat_message import ChatMessage

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(self, db: Session, tenant_id: int = None):
        self.db = db
        self.tenant_id = tenant_id

    def create_or_resume_session(
        self,
        fingerprint: str,
        visitor_uuid: str,
        ip: str,
        user_agent: str,
        browser: str = "Unknown",
        os: str = "Unknown",
        device_type: str = "desktop",
        commit: bool = True
    ) -> ChatSession:
        """
        Prevents duplicate queue cards by checking for existing active sessions.
        Uses fingerprint hash to identify returning visitors.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=30)
        
        # Check for existing active session
        stmt = (
            select(ChatSession)
            .where(
                and_(
                    ChatSession.visitor_uuid == visitor_uuid,
                    ChatSession.session_status.in_([SessionStatus.ACTIVE]),
                    ChatSession.last_activity_at >= cutoff,
                    ChatSession.tenant_id == self.tenant_id if self.tenant_id else ChatSession.tenant_id
                )
            )
            .order_by(ChatSession.created_at.desc())
            .limit(1)
        )
        
        result = self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update last activity and return existing session
            existing.last_activity_at = datetime.utcnow()
            existing.last_activity_utc = datetime.utcnow()
            existing.ip_metadata_dict = {
                "ip": ip,
                "user_agent": user_agent,
                "browser": browser,
                "os": os,
                "device_type": device_type
            }
            if commit:
                self.db.commit()
                self.db.refresh(existing)
            else:
                self.db.flush()
            return existing
        
        # Create new session
        session_suffix = hashlib.sha256(
            f"{fingerprint}{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:7]
        session_id = f"session_{session_suffix}"
        
        now = datetime.utcnow()
        session = ChatSession(
            session_id=session_id,
            visitor_uuid=visitor_uuid,
            session_status=SessionStatus.ACTIVE,
            current_mode=ConversationMode.BOT,
            conversation_mode=ConversationMode.BOT,  # Keep for compatibility
            tenant_id=self.tenant_id or 1,
            created_at=now,
            started_at_utc=now,
            started_at_local=now,
            last_activity_at=now,
            last_activity_utc=now,
            initial_ip=ip,
            browser=browser,
            os=os,
            device_type=device_type,
            user_agent=user_agent
        )
        
        # Set ip_metadata using the property
        session.ip_metadata_dict = {
            "ip": ip,
            "user_agent": user_agent,
            "browser": browser,
            "os": os,
            "device_type": device_type
        }
        
        self.db.add(session)
        if commit:
            self.db.commit()
            self.db.refresh(session)
        else:
            self.db.flush()
        return session

    def update_session_from_lead_form(
        self,
        session_id: str,
        lead_data: dict,
        commit: bool = True
    ) -> ChatSession:
        """
        Updates session with lead form data and proper display name.
        Called when visitor submits lead form through bot.
        """
        session = self.db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.tenant_id == (self.tenant_id if hasattr(self, 'tenant_id') else ChatSession.tenant_id)
        ).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        # Extract name from lead form
        full_name = lead_data.get("name") or lead_data.get("fullName", "")
        
        # Update session with lead info
        session.lead_name = full_name
        session.lead_email = lead_data.get("email")
        session.lead_phone = lead_data.get("phone")
        session.lead_company = lead_data.get("company")
        session.last_activity_at = datetime.utcnow()
        session.last_activity_utc = datetime.utcnow()
        
        # Calculate lead score
        session.lead_score = self._calculate_lead_score(lead_data)
        session.lead_status = self._get_lead_status_from_score(session.lead_score)
        
        if commit:
            self.db.commit()
            self.db.refresh(session)
        else:
            self.db.flush()
        return session

    def get_active_sessions(self, tenant_id: int = None) -> List[ChatSession]:
        """
        Get all truly active sessions:
        1. Marked ACTIVE/BOT/WAITING/HUMAN in DB
        2. AND Not deleted
        3. AND (Connected via WebSocket OR Active within the last 24 hours)
        4. AND Deduplicated by visitor_uuid (only most recent) using SQL for performance
        """
        from datetime import datetime, timedelta
        from sqlalchemy import func, and_, select, desc
        
        # 24h window — bot sessions must be visible even after client disconnects
        stale_cutoff = datetime.utcnow() - timedelta(hours=24)
        
        # 1. Base status conditions
        conditions = [
            ChatSession.session_status.in_([SessionStatus.ACTIVE, SessionStatus.BOT, SessionStatus.WAITING, SessionStatus.HUMAN]),
            ChatSession.is_deleted == False
        ]
        if tenant_id:
            conditions.append(ChatSession.tenant_id == tenant_id)

        # 🚀 JUNK SUPPRESSION: Only show sessions with interaction OR brand new visitors
        # Interaction = user message exists OR lead info present
        from sqlalchemy import exists, or_
        
        has_user_message = exists().where(
            and_(
                ChatMessage.session_id == ChatSession.session_id,
                ChatMessage.message_type == 'user'
            )
        )
        
        has_lead_info = or_(
            ChatSession.is_lead == True,
            ChatSession.lead_email != None,
            ChatSession.lead_phone != None
        )
        
        # Grace period: Show bots born in the last 15 minutes even if no interaction (allows agents to see new traffic)
        grace_period_cutoff = datetime.utcnow() - timedelta(minutes=15)
        is_fresh = ChatSession.created_at >= grace_period_cutoff
        
        conditions.append(
            or_(
                has_user_message,
                has_lead_info,
                is_fresh
            )
        )

        # 2. SQL Window Function for deduplication
        # We find the latest session per visitor that matches the active criteria
        inner_stmt = (
            select(
                ChatSession.id,
                func.row_number().over(
                    partition_by=ChatSession.visitor_uuid,
                    order_by=desc(ChatSession.last_activity_at)
                ).label('rn')
            ).where(and_(*conditions))
        ).subquery()

        # 3. Filter for rn = 1 and fetch the full objects
        # We also apply the activity cutoff here if they aren't online
        # (WebSocket check is still done in Python because it's in-memory status)
        
        # Get candidate sessions
        candidates = (
            self.db.query(ChatSession)
            .join(inner_stmt, ChatSession.id == inner_stmt.c.id)
            .filter(inner_stmt.c.rn == 1)
            .order_by(desc(ChatSession.last_activity_at))
            .all()
        )
        
        from app.services.websocket_manager import manager
        
        filtered_sessions = []
        for s in candidates:
            # Check online status or recent activity
            is_online = manager.has_client(s.visitor_uuid)
            is_recent = s.last_activity_at >= stale_cutoff if s.last_activity_at else False
            
            if is_online or is_recent:
                filtered_sessions.append(s)
                
        return filtered_sessions

    def agent_takeover(self, session_id: str, agent_name: str, commit: bool = True) -> ChatSession:
        """Handle agent takeover of bot conversation."""
        session = self.db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.tenant_id == (self.tenant_id if hasattr(self, 'tenant_id') else ChatSession.tenant_id)
        ).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        session.current_mode = ConversationMode.HUMAN
        session.conversation_mode = ConversationMode.HUMAN  # Keep for compatibility
        session.session_status = SessionStatus.ACTIVE
        session.agent_name = agent_name
        session.is_locked = True
        session.agent_joined = True
        session.last_activity_at = datetime.utcnow()
        session.last_activity_utc = datetime.utcnow()
        
        if commit:
            self.db.commit()
            self.db.refresh(session)
        else:
            self.db.flush()
        return session

    def end_session(self, session_id: str, commit: bool = True) -> ChatSession:
        """End a chat session."""
        session = self.db.query(ChatSession).filter(
            ChatSession.session_id == session_id,
            ChatSession.tenant_id == (self.tenant_id if hasattr(self, 'tenant_id') else ChatSession.tenant_id)
        ).first()
            
        if not session:
            raise ValueError(f"Session {session_id} not found")
        
        session.session_status = SessionStatus.CLOSED
        session.is_locked = False
        session.agent_joined = False
        session.last_activity_at = datetime.utcnow()
        session.last_activity_utc = datetime.utcnow()
        session.ended_at_utc = datetime.utcnow()
        session.ended_at_local = datetime.utcnow()
        
        if commit:
            self.db.commit()
            self.db.refresh(session)
        else:
            self.db.flush()
        return session

    def _calculate_lead_score(self, lead_data: dict) -> int:
        """Calculate lead score based on form completeness and content."""
        score: int = 0
        
        # Base score for form submission
        score += 20
        
        # Score for each filled field
        fields = ["name", "email", "phone", "company", "interest"]
        for field in fields:
            if lead_data.get(field):
                score += 10
        
        # Bonus for business email domains
        email = lead_data.get("email", "")
        if email and not any(domain in email.lower() for domain in ["gmail", "yahoo", "hotmail", "outlook"]):
            score += 15
        
        # Bonus for company name
        if lead_data.get("company"):
            score += 10
        
        return min(score, 100)  # Cap at 100

    def _get_lead_status_from_score(self, score: int) -> str:
        """Convert numeric score to status string."""
        if score >= 70:
            return "HOT"
        elif score >= 40:
            return "WARM"
        else:
            return "COLD"

    def _get_display_name(self, session: ChatSession) -> str:
        """Get proper display name for session."""
        if session.lead_name:
            return session.lead_name
        
        # Use visitor UUID last 6 characters
        return f"Visitor #{session.visitor_uuid[-6:].upper()}"

# Module-level functions for backward compatibility
def get_active_session(db: Session, session_id: str, tenant_id: int = None) -> Optional[ChatSession]:
    """Get active session by session_id (UUID). Module-level function for backward compatibility."""
    from sqlalchemy import select, and_
    
    try:
        # Try to find by visitor_uuid first (most common case) - get the most recent one
        stmt = (
            select(ChatSession)
            .where(
                and_(
                    ChatSession.visitor_uuid == session_id,
                    ChatSession.session_status.in_([SessionStatus.ACTIVE, SessionStatus.CLOSED]),
                    ChatSession.tenant_id == tenant_id
                )
            )
            .order_by(ChatSession.last_activity_at.desc())
            .limit(1)
        )
        result = db.execute(stmt)
        session = result.scalar_one_or_none()
        
        if session:
            return session
            
        # If not found by visitor_uuid, try by session_id (legacy) - get the most recent one
        stmt = (
            select(ChatSession)
            .where(
                and_(
                    ChatSession.session_id == session_id,
                    ChatSession.session_status.in_([SessionStatus.ACTIVE, SessionStatus.CLOSED]),
                    ChatSession.tenant_id == tenant_id
                )
            )
            .order_by(ChatSession.last_activity_at.desc())
            .limit(1)
        )
        result = db.execute(stmt)
        return result.scalar_one_or_none()
        
    except Exception as e:
        logger.error(f"Error getting active session: {e}")
        return None

# Module-level function for backward compatibility with chatbot.py
def create_session(
    db: Session,
    tenant_id: int,
    ip_address: str,
    country: str = None,
    city: str = None,
    timezone_str: str = None,
    user_agent: str = None,
    browser: str = "Unknown",
    os_name: str = "Unknown", 
    device_type: str = "desktop",
    fingerprint: str = None,
    visitor_uuid: str = None,
    lead_id: int = None,
    commit: bool = True
) -> ChatSession:
    """Create a new chat session (synchronous version for backward compatibility)."""
    import uuid
    import hashlib
    
    # Generate visitor_uuid if not provided
    if not visitor_uuid:
        visitor_uuid = str(uuid.uuid4())
    
    # Generate session_id (required field)
    session_suffix = hashlib.sha256(
        f"{fingerprint or visitor_uuid}{datetime.utcnow().isoformat()}".encode()
    ).hexdigest()[:7]
    session_id = f"session_{session_suffix}"
    
    now = datetime.utcnow()
    
    # Create new session
    session = ChatSession(
        session_id=session_id,  # Add the required session_id
        visitor_uuid=visitor_uuid,
        session_status=SessionStatus.ACTIVE,
        current_mode=ConversationMode.BOT,
        conversation_mode=ConversationMode.BOT,
        created_at=now,
        started_at_utc=now,
        started_at_local=now,
        last_activity_at=now,
        last_activity_utc=now,
        initial_ip=ip_address,
        country=country,
        city=city,
        timezone=timezone_str,
        user_agent=user_agent,
        browser=browser,
        os=os_name,
        device_type=device_type,
        visitor_fingerprint=fingerprint,
        tenant_id=tenant_id or 1,
        message_count=0
    )
    
    # Set ip_metadata using the property
    if ip_address or user_agent:
        session.ip_metadata_dict = {
            "ip": ip_address,
            "user_agent": user_agent,
            "browser": browser,
            "os": os_name,
            "device_type": device_type
        }
    
    db.add(session)
    if commit:
        db.commit()
        db.refresh(session)
    else:
        db.flush()
    
    return session

def save_message(db: Session, session: ChatSession, message_text: str, message_type: str, commit: bool = True) -> ChatMessage:
    """Save a message to the database (synchronous version for backward compatibility)."""
    now = datetime.utcnow()
    
    # Fix potential UTF-16 encoding issues
    if message_text and '\x00' in message_text:
        message_text = message_text.replace('\x00', '')
        logger.warning(f"Fixed UTF-16 encoding in message for session {session.session_id}")
    
    # --- DEDUPLICATION LOGIC ---
    from datetime import timedelta
    stale_cutoff = now - timedelta(seconds=3)
    duplicate = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.session_id == session.session_id,
            ChatMessage.message_type == message_type,
            ChatMessage.message_text == message_text,
            ChatMessage.created_at_utc >= stale_cutoff
        )
        .first()
    )
    if duplicate:
        return duplicate
    # ---------------------------
    
    message = ChatMessage(
        session_id=session.session_id,  # Use session_id (string) not id (BigInteger)
        tenant_id=session.tenant_id,   # 🧪 CRITICAL: Link message to session's tenant
        message_type=message_type,
        message_text=message_text,
        created_at=now,
        created_at_utc=now,
        created_at_local=now
    )
    
    db.add(message)
    
    # Update session message count and activity
    session.message_count = (session.message_count or 0) + 1
    session.last_activity_at = now
    session.last_activity_utc = now
    
    if commit:
        db.commit()
        db.refresh(message)
    else:
        db.flush()
    
    return message


def update_chat_state(db: Session, session: ChatSession, new_state: str, commit: bool = True) -> None:
    """Update the chat state of a session."""
    session.chat_state = str(new_state).upper()
    if commit:
        db.commit()
    else:
        db.flush()

def close_session(db: Session, session_id: str, tenant_id: int = None, commit: bool = True) -> bool:
    """Close a session by session_id (synchronous version for backward compatibility)."""
    try:
        # Try to find by visitor_uuid first
        session = get_active_session(db, session_id, tenant_id)
        
        if session:
            session.session_status = SessionStatus.CLOSED
            session.is_active = False
            session.ended_at_utc = datetime.utcnow()
            session.ended_at_local = datetime.utcnow()
            session.last_activity_at = datetime.utcnow()
            session.last_activity_utc = datetime.utcnow()
            
            if commit:
                db.commit()
            else:
                db.flush()
            return True
            
        return False
        
    except Exception as e:
        logger.error(f"Error closing session: {e}")
        return False