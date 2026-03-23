import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.intent_config import IntentConfig
from app.db.session import SessionLocal

def check_intents():
    db = SessionLocal()
    try:
        intents = db.query(IntentConfig).all()
        print(f"Total Intents: {len(intents)}")
        for intent in intents:
            print(f"Key: {intent.intent_key}")
            print(f"  Keywords: {intent.keywords}")
            print(f"  Response (first 50 chars): {intent.response_text[:50] if intent.response_text else 'N/A'}")
            print("-" * 20)
    finally:
        db.close()

if __name__ == "__main__":
    check_intents()
