import sys
import os
import time
import logging

# Add backend to path
sys.path.append(r'c:\Users\Harsh kumar\Desktop\GTT_smartbot\Backend_bot')

from app.db.session import SessionLocal
from app.services.session_service import SessionService
from app.api.live_chat import format_session_for_crm
from app.models.chat_message import ChatMessage
from sqlalchemy import select, func, and_

def profile_conversations(tenant_id=1):
    db = SessionLocal()
    try:
        print(f"--- Profiling for Tenant {tenant_id} ---")
        start_time = time.time()
        
        # 1. Fetch sessions
        service = SessionService(db)
        sessions = service.get_active_sessions(tenant_id=tenant_id)
        fetch_time = time.time() - start_time
        print(f"Fetched {len(sessions)} active sessions in {fetch_time:.4f}s")
        
        if not sessions:
            return

        # 2. Batch count (My optimization)
        batch_start = time.time()
        session_ids = [s.session_id for s in sessions]
        user_msg_counts = {}
        if session_ids:
            # Note: Using the exact logic from live_chat.py
            stmt = (
                select(ChatMessage.session_id, func.count(ChatMessage.id))
                .where(
                    and_(
                        ChatMessage.session_id.in_(session_ids),
                        ChatMessage.message_type == 'user'
                    )
                )
                .group_by(ChatMessage.session_id)
            )
            counts = db.execute(stmt).all()
            user_msg_counts = {sid: count for sid, count in counts}
        batch_time = time.time() - batch_start
        print(f"Batch counted user messages in {batch_time:.4f}s")
        
        # 3. Format sessions
        format_start = time.time()
        conversations = [
            format_session_for_crm(s, db=db, user_msg_count=user_msg_counts.get(s.session_id, 0)) 
            for s in sessions
        ]
        format_time = time.time() - format_start
        print(f"Formatted {len(conversations)} conversations in {format_time:.4f}s")
        
        total_time = time.time() - start_time
        print(f"Total Logic Time: {total_time:.4f}s")
        
        # Analytics on data
        with_user_msgs = [c for c in conversations if c['user_message_count'] > 0]
        print(f"Sessions with user messages: {len(with_user_msgs)}")
        print(f"Sessions without user messages: {len(conversations) - len(with_user_msgs)}")

    finally:
        db.close()

if __name__ == "__main__":
    # Defaulting to tenant 1, but we might need to find which tenant is busy
    profile_conversations(1)
