
import sys
import os
import time
from sqlalchemy import select, and_, func

# Add app directory to path
sys.path.append(os.getcwd())

from app.db.session import SessionLocal
from app.models.chat_session import ChatSession, SessionStatus
from app.models.chat_message import ChatMessage
from app.services.session_service import SessionService

def test_perf():
    db = SessionLocal()
    try:
        tenant_id = 1 # Update if needed
        print(f"Testing performance for tenant {tenant_id}...")
        
        # 1. Test get_active_sessions
        start = time.time()
        session_service = SessionService(db)
        sessions = session_service.get_active_sessions(tenant_id=tenant_id)
        end = time.time()
        print(f"get_active_sessions found {len(sessions)} sessions in {end - start:.4f}s")
        
        if not sessions:
            print("No active sessions found.")
            return

        session_ids = [s.session_id for s in sessions]
        
        # 2. Test batch count query
        start = time.time()
        counts = db.execute(
            select(ChatMessage.session_id, func.count(ChatMessage.id))
            .where(
                and_(
                    ChatMessage.session_id.in_(session_ids),
                    ChatMessage.message_type == 'user'
                )
            )
            .group_by(ChatMessage.session_id)
        ).all()
        user_msg_counts = {sid: count for sid, count in counts}
        end = time.time()
        print(f"Batch counting {len(session_ids)} sessions took {end - start:.4f}s")
        
        # 3. Test individual counts (The old way)
        start = time.time()
        for s in sessions[:10]: # Just test first 10
            db.query(func.count(ChatMessage.id)).filter(
                ChatMessage.session_id == s.session_id,
                ChatMessage.message_type == 'user'
            ).scalar()
        end = time.time()
        print(f"Individual counting for 10 sessions took {end - start:.4f}s (Projected for total: {(end - start) * len(sessions) / 10:.4f}s)")
        
    finally:
        db.close()

if __name__ == "__main__":
    test_perf()
