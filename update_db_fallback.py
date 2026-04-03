
from sqlalchemy import text
from app.db.session import SessionLocal

def update_fallback_message():
    new_message = """Thankyou, We will arrange a call for you shortly. 
You can discuss all your questions with our team during the meeting. 
Regarding your data etc..., Our team provide you appropriate solution."""
    
    db = SessionLocal()
    try:
        # Update the FALLBACK_GENERIC response in intent_configs
        # Use NVARCHAR/Unicode handling for SQL Server
        db.execute(text("UPDATE intent_configs SET response_text = :msg WHERE intent_key = 'FALLBACK_GENERIC'"), {"msg": new_message})
        db.commit()
        print("Successfully updated FALLBACK_GENERIC message in database.")
    except Exception as e:
        print(f"Error updating database: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    update_fallback_message()
