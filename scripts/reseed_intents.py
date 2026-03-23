from sqlalchemy import text
from app.db.session import SessionLocal
from seed_intents import seed_intents

def reseed_with_clean_ids():
    db = SessionLocal()
    try:
        print("--- DATABASE RESET START ---")
        
        # 1. Truncate table (Faster and resets identity automatically in SQL Server)
        print("Clearing table using TRUNCATE...")
        db.execute(text("TRUNCATE TABLE intent_configs"))
        db.commit()
        
        # Double check if empty
        count = db.execute(text("SELECT COUNT(*) FROM intent_configs")).scalar()
        print(f"Current row count: {count}")
        
        # 2. Safety reset of identity (optional but good for MS SQL)
        print("Forcing identity counter to 0...")
        db.execute(text("DBCC CHECKIDENT ('intent_configs', RESEED, 0)"))
        db.commit()
        
        print("Table cleared and identity reset.")
        
        # 3. Run original seed logic
        print("Seeding intents from seed_intents.py...")
        from seed_intents import seed_intents
        seed_intents()
        
        # Final Verification
        final_count = db.execute(text("SELECT COUNT(*) FROM intent_configs")).scalar()
        print(f"Final row count: {final_count}")
        print("--- DATABASE RESET COMPLETE ---")
        print("Please refresh your SQL view now.")
        
    except Exception as e:
        print(f"ERROR: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    reseed_with_clean_ids()
