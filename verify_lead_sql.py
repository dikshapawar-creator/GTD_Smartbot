import sys
import os
sys.path.append(os.getcwd())

from app.db.session import SessionLocal
from app.models.lead import Lead
from sqlalchemy import select

def verify():
    db = SessionLocal()
    try:
        # Try to query the leads table
        stmt = select(Lead).limit(1)
        result = db.execute(stmt).first()
        print("✅ Successfully queried 'leads' table!")
        if result:
            print(f"Sample Lead ID: {result[0].id}")
        else:
            print("Table is empty, but query succeeded.")
    except Exception as e:
        print(f"❌ Query failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    verify()
