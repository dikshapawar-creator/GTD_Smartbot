import secrets
from sqlalchemy import create_engine, text
from app.core.config import settings

def migrate_tenant_keys():
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        # 1. Add column if not exists (MSSQL syntax)
        print("Checking for tenant_key column...")
        check_col = conn.execute(text(
            "SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('tenants') AND name = 'tenant_key'"
        )).fetchone()
        
        if not check_col:
            print("Adding tenant_key column...")
            conn.execute(text("ALTER TABLE tenants ADD tenant_key VARCHAR(100) NULL"))
            conn.commit()

        # 2. Populate keys
        print("Populating tenant_keys...")
        tenants = conn.execute(text("SELECT id, name FROM tenants WHERE tenant_key IS NULL")).fetchall()
        for t_id, t_name in tenants:
            # Generate secure key: prefix_random
            prefix = t_name.lower().replace(" ", "_")[:20]
            secure_token = secrets.token_urlsafe(12)
            new_key = f"{prefix}_{secure_token}"
            
            print(f"Assigning key to {t_name}: {new_key}")
            conn.execute(
                text("UPDATE tenants SET tenant_key = :key WHERE id = :id"),
                {"key": new_key, "id": t_id}
            )
        conn.commit()

        # 3. Make NOT NULL and UNIQUE
        print("Setting NOT NULL and UNIQUE constraints...")
        # Check if already unique
        check_ui = conn.execute(text(
            "SELECT 1 FROM sys.indexes WHERE name = 'uq_tenant_key' AND object_id = OBJECT_ID('tenants')"
        )).fetchone()
        
        if not check_ui:
            # First ensure no nulls (should be none now)
            conn.execute(text("ALTER TABLE tenants ALTER COLUMN tenant_key VARCHAR(100) NOT NULL"))
            conn.execute(text("ALTER TABLE tenants ADD CONSTRAINT uq_tenant_key UNIQUE (tenant_key)"))
            conn.commit()
            print("Constraints applied.")
        else:
            print("Constraints already exist.")

if __name__ == "__main__":
    migrate_tenant_keys()
