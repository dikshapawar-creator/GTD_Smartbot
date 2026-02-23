"""One-time migration: add Human Agent Takeover columns to chat_sessions."""
from app.db.session import engine
from sqlalchemy import text

def migrate():
    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(text(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'chat_sessions' AND COLUMN_NAME = 'status'"
        ))
        if result.fetchone():
            print("Columns already exist. Skipping migration.")
            return

        conn.execute(text(
            "ALTER TABLE chat_sessions ADD "
            "status VARCHAR(20) NOT NULL DEFAULT 'bot', "
            "assigned_agent_id INT NULL, "
            "is_locked BIT NOT NULL DEFAULT 0"
        ))
        conn.commit()
        print("Migration complete: added status, assigned_agent_id, is_locked columns.")

if __name__ == "__main__":
    migrate()
