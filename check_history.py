
from sqlalchemy import text
from app.db.session import SessionLocal

def check_visitor_history(visitor_uuid):
    db = SessionLocal()
    try:
        # Check all sessions for this visitor
        sessions = db.execute(text(
            "SELECT session_id, visitor_uuid, session_status, created_at, last_activity_at "
            "FROM chat_sessions WHERE visitor_uuid = :uuid OR visitor_uuid LIKE :uuid_partial "
            "ORDER BY created_at DESC"
        ), {"uuid": visitor_uuid, "uuid_partial": f"%{visitor_uuid[-8:]}"}).fetchall()
        
        print(f"\n--- Sessions for {visitor_uuid} ---")
        for s in sessions:
            print(f"ID: {s.session_id} | Status: {s.session_status} | Created: {s.created_at}")
            
            # Check messages for EACH session
            msgs = db.execute(text(
                "SELECT id, message_type, message_text, created_at_utc "
                "FROM chat_messages WHERE session_id = :sid ORDER BY created_at_utc ASC"
            ), {"sid": s.session_id}).fetchall()
            
            print(f"  Messages ({len(msgs)}):")
            for m in msgs:
                print(f"    [{m.message_type}] {m.message_text[:30]}... ({m.created_at_utc})")
                
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    # Based on the screenshot, the visitor uuid ends in something like '623affad36d1' (hard to read)
    # But I can search for 'diksha' in lead_name too
    db = SessionLocal()
    visitor = db.execute(text("SELECT visitor_uuid FROM chat_sessions WHERE lead_name LIKE '%diksha%' LIMIT 1")).scalar()
    db.close()
    
    if visitor:
        check_visitor_history(visitor)
    else:
        print("Visitor 'diksha' not found in database.")
