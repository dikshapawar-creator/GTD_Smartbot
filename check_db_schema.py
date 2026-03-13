#!/usr/bin/env python3
"""
Check database schema to verify visitor_uuid column exists
"""
from sqlalchemy import create_engine, text
from app.core.config import settings

def check_schema():
    engine = create_engine(settings.DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            # Check if visitor_uuid column exists
            result = conn.execute(text("""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'chat_sessions' 
                AND COLUMN_NAME = 'visitor_uuid'
            """))
            
            row = result.fetchone()
            if row:
                print(f"✅ visitor_uuid column exists:")
                print(f"   Column: {row[0]}")
                print(f"   Type: {row[1]}")
                print(f"   Nullable: {row[2]}")
            else:
                print("❌ visitor_uuid column does NOT exist")
                
            # Check all columns in chat_sessions table
            print("\n📋 All columns in chat_sessions table:")
            result = conn.execute(text("""
                SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'chat_sessions'
                ORDER BY ORDINAL_POSITION
            """))
            
            for row in result:
                print(f"   {row[0]} ({row[1]}) - Nullable: {row[2]}")
                
    except Exception as e:
        print(f"❌ Error checking schema: {e}")

if __name__ == "__main__":
    check_schema()