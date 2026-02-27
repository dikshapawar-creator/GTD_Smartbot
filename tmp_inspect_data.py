
import sys
import os
from sqlalchemy import create_engine, text

# Add the parent directory to sys.path to import app modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.config import settings

def inspect_data():
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        print("\n--- Users Table ---")
        users = conn.execute(text("SELECT id, email, tenant_id FROM users")).fetchall()
        for u in users:
            print(f"ID: {u.id} | Email: {u.email} | TenantID: {u.tenant_id}")
            
        print("\n--- Leads Table ---")
        leads = conn.execute(text("SELECT TOP 5 id, name, tenant_id, is_deleted FROM leads ORDER BY created_at DESC")).fetchall()
        for l in leads:
            print(f"ID: {l.id} | Name: {l.name} | TenantID: {l.tenant_id} | Deleted: {l.is_deleted}")
            
        print("\n--- Tenants Table ---")
        tenants = conn.execute(text("SELECT id, name FROM tenants")).fetchall()
        for t in tenants:
            print(f"ID: {t.id} | Name: {t.name}")

if __name__ == "__main__":
    inspect_data()
