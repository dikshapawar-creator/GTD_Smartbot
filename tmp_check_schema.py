
import sys
import os
from sqlalchemy import create_engine, text, inspect

# Add the parent directory to sys.path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.config import settings

def check_schema():
    engine = create_engine(settings.DATABASE_URL)
    inspector = inspect(engine)
    
    tables = ['leads', 'lead_status_history', 'chat_sessions']
    
    for table_name in tables:
        print(f"\n--- Columns in {table_name} ---")
        columns = inspector.get_columns(table_name)
        for column in columns:
            print(f"{column['name']}: {column['type']}")

if __name__ == "__main__":
    check_schema()
