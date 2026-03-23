import os
import sys
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

# Add app to path
sys.path.append(os.getcwd())

from app.core.config import settings
from app.db.session import SessionLocal

def fix_chat_states():
    db = SessionLocal()
    try:
        print("Cleaning and updating chat_sessions.chat_state...")
        # 1. Update GREETING to START
        db.execute(text("UPDATE chat_sessions SET chat_state = 'START' WHERE chat_state = 'GREETING' OR chat_state = 'greeting'"))
        # 2. Cleanup 'CHATSTATE.X' or 'ChatState.X' prefixes
        db.execute(text("UPDATE chat_sessions SET chat_state = REPLACE(chat_state, 'ChatState.', '') WHERE chat_state LIKE 'ChatState.%'"))
        db.execute(text("UPDATE chat_sessions SET chat_state = REPLACE(chat_state, 'CHATSTATE.', '') WHERE chat_state LIKE 'CHATSTATE.%'"))
        # 3. Uppercase everything
        db.execute(text("UPDATE chat_sessions SET chat_state = UPPER(chat_state)"))
        db.commit()
        print("Successfully updated records.")
    except Exception as e:
        print(f"Error updating states: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    fix_chat_states()
