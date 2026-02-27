from sqlalchemy import create_engine, text
import json

DATABASE_URL = "mssql+pyodbc://sa:YourStrong%40Password@localhost:1433/smartbot_db?driver=ODBC+Driver+17+for+SQL+Server"
engine = create_engine(DATABASE_URL)

def dump_data():
    output = {}
    try:
        with engine.connect() as conn:
            # Check users
            users = conn.execute(text("SELECT id, email, tenant_id, token_version FROM users")).fetchall()
            output["users"] = [dict(row._mapping) for row in users]
            
            # Check tenants
            tenants = conn.execute(text("SELECT id, name FROM tenants")).fetchall()
            output["tenants"] = [dict(row._mapping) for row in tenants]
            
            # Check leads (first 5)
            leads = conn.execute(text("SELECT TOP 5 id, name, tenant_id FROM leads")).fetchall()
            output["leads_sample"] = [dict(row._mapping) for row in leads]
            
            # Check leads tenant count
            lead_counts = conn.execute(text("SELECT tenant_id, COUNT(*) as count FROM leads GROUP BY tenant_id")).fetchall()
            output["lead_counts_by_tenant"] = [dict(row._mapping) for row in lead_counts]

        with open(r"c:\Users\Harsh kumar\Desktop\GTT_smartbot\Backend_bot\db_dump.json", "w") as f:
            json.dump(output, f, indent=4, default=str)
        print("Done")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    dump_data()
