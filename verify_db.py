from sqlalchemy import create_engine, text
import os

DATABASE_URL = "mssql+pyodbc://sa:YourStrong%40Password@localhost:1433/smartbot_db?driver=ODBC+Driver+17+for+SQL+Server"

engine = create_engine(DATABASE_URL)

def check_users():
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT id, email, token_version, tenant_id FROM users")).fetchall()
            print("--- USERS TABLE ---")
            for row in result:
                print(f"ID: {row.id} | Email: {row.email} | Token Version: {row.token_version} | Tenant: {row.tenant_id}")
            
            leads_count = conn.execute(text("SELECT COUNT(*) FROM leads")).scalar()
            print(f"\nTotal Leads in DB: {leads_count}")
            
            lead_tenants = conn.execute(text("SELECT DISTINCT tenant_id FROM leads")).fetchall()
            print(f"Distinct Lead Tenant IDs: {[r[0] for r in lead_tenants]}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_users()
