from app.db.session import SessionLocal
from sqlalchemy import text
import sys

def inspect_session(session_id):
    db = SessionLocal()
    try:
        query = text(f"SELECT session_id, initial_ip, country, city, browser, os, visitor_fingerprint FROM chat_sessions WHERE session_id = '{session_id}'")
        res = db.execute(query).fetchone()
        if res:
            cols = ["session_id", "initial_ip", "country", "city", "browser", "os", "visitor_fingerprint"]
            data = dict(zip(cols, res))
            print(f"SESSION DATA: {data}")
        else:
            print("Session not found.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        inspect_session(sys.argv[1])
    else:
        print("Usage: python inspect_session.py <session_id>")
