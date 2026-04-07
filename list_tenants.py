import sys
import os

# Add backend to path
sys.path.append(r'c:\Users\Harsh kumar\Desktop\GTT_smartbot\Backend_bot')

from app.db.session import SessionLocal
from app.models.chat_session import ChatSession
from sqlalchemy import func

def list_tenants():
    db = SessionLocal()
    try:
        counts = db.query(
            ChatSession.tenant_id, 
            func.count(ChatSession.id)
        ).group_by(ChatSession.tenant_id).all()
        
        print("Tenant ID | Session Count")
        print("-------------------------")
        for tid, count in counts:
            print(f"{tid:9} | {count:13}")
            
    finally:
        db.close()

if __name__ == "__main__":
    list_tenants()
