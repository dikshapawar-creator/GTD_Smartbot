#!/usr/bin/env python3
"""
Create a migration to change JSON columns to TEXT to avoid parsing issues.
"""

import os
import sys

# Add current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from app.core.config import settings

def create_migration():
    """Create migration to change JSON columns to TEXT."""
    engine = create_engine(settings.DATABASE_URL)
    
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            
            try:
                print("🔄 Converting JSON columns to TEXT...")
                
                # For SQL Server, we need to alter the columns
                # First, let's check the current column types
                result = conn.execute(text("""
                    SELECT COLUMN_NAME, DATA_TYPE 
                    FROM INFORMATION_SCHEMA.COLUMNS 
                    WHERE TABLE_NAME = 'intent_configs' 
                    AND COLUMN_NAME IN ('keywords', 'metadata_json')
                """))
                
                columns = result.fetchall()
                print(f"Current column types: {dict(columns)}")
                
                # Convert keywords column to NVARCHAR(MAX) if it's not already
                conn.execute(text("""
                    ALTER TABLE intent_configs 
                    ALTER COLUMN keywords NVARCHAR(MAX)
                """))
                print("✅ Converted keywords column to NVARCHAR(MAX)")
                
                # Convert metadata_json column to NVARCHAR(MAX) if it's not already
                conn.execute(text("""
                    ALTER TABLE intent_configs 
                    ALTER COLUMN metadata_json NVARCHAR(MAX)
                """))
                print("✅ Converted metadata_json column to NVARCHAR(MAX)")
                
                trans.commit()
                print("✅ Migration completed successfully!")
                
            except Exception as e:
                trans.rollback()
                raise e
                
    except Exception as e:
        print(f"❌ Migration error: {e}")
        raise

if __name__ == "__main__":
    create_migration()