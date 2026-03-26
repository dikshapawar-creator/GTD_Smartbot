
import sys
import os
# Add the project directory to sys.path
sys.path.append(os.getcwd())

from sqlalchemy import create_engine, text
from app.core.config import settings

def check():
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        print("--- TENANTS ---")
        tenants = conn.execute(text("SELECT id, name, tenant_key FROM tenants")).fetchall()
        for t in tenants:
            print(f"ID: {t.id}, Name: {t.name}, Key: {t.tenant_key}")
        
        print("\n--- BOT CONFIGS ---")
        configs = conn.execute(text("SELECT id, tenant_id, chatbot_name FROM bot_config")).fetchall()
        for c in configs:
            print(f"ID: {c.id}, TenantID: {c.tenant_id}, Name: {c.chatbot_name}")

if __name__ == "__main__":
    check()
