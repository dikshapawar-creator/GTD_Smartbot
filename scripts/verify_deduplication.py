import sys
import os
from datetime import datetime, timedelta

# Add the parent directory to sys.path to import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.models.chat_session import ChatSession, SessionStatus
from app.services.session_service import SessionService

def test_deduplication():
    db = SessionLocal()
    service = SessionService(db)
    
    visitor_uuid = "test-visitor-dedup-123"
    
    try:
        # 1. Create two active sessions for the same visitor
        now = datetime.utcnow()
        old_time = now - timedelta(minutes=10)
        new_time = now
        
        old_session = ChatSession(
            session_id="session_old_123",
            visitor_uuid=visitor_uuid,
            session_status=SessionStatus.ACTIVE,
            created_at=old_time,
            last_activity_at=old_time,
            last_activity_utc=old_time,
            started_at_utc=old_time,
            started_at_local=old_time,
            tenant_id=1,
            is_active=True
        )
        
        new_session = ChatSession(
            session_id="session_new_123",
            visitor_uuid=visitor_uuid,
            session_status=SessionStatus.ACTIVE,
            created_at=new_time,
            last_activity_at=new_time,
            last_activity_utc=new_time,
            started_at_utc=new_time,
            started_at_local=new_time,
            tenant_id=1,
            is_active=True
        )
        
        db.add(old_session)
        db.add(new_session)
        db.commit()
        
        print(f"Created two sessions for {visitor_uuid}")
        
        # 2. Call get_active_sessions
        active_sessions = service.get_active_sessions()
        
        # 3. Filter for our test visitor
        visitor_sessions = [s for s in active_sessions if s.visitor_uuid == visitor_uuid]
        
        print(f"Found {len(visitor_sessions)} sessions in active list for {visitor_uuid}")
        
        assert len(visitor_sessions) == 1, f"Expected 1 session, found {len(visitor_sessions)}"
        assert visitor_sessions[0].session_id == "session_new_123", f"Expected latest session, found {visitor_sessions[0].session_id}"
        
        print("✅ Verification Successful: Deduplication works!")
        
    finally:
        # Cleanup
        db.query(ChatSession).filter(ChatSession.visitor_uuid == visitor_uuid).delete()
        db.commit()
        db.close()

if __name__ == "__main__":
    test_deduplication()
